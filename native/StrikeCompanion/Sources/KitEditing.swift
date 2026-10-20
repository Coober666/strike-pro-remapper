import Foundation

/// Only confirmed, writable per-pad bytes. Layer B's maximum velocity and all reserved bytes stay untouched.
public enum KitParameter: String, CaseIterable, Sendable, Identifiable {
    case aLevel, aPan, aDecay, aPitch, aFine, aCutoff, aFilter, aVelocityDecay, aVelocityPitch
    case aVelocityFilter, aVelocityVolume, aVelocityMinimum, aVelocityMaximum, aLoop
    case bLevel, bPan, bDecay, bPitch, bFine, bCutoff, bFilter, bVelocityDecay, bVelocityPitch
    case bVelocityFilter, bVelocityVolume, bVelocityMinimum, bLoop
    case reverb, fx1, fx2, eqComp, priority, muteGroup, noteOff, midiChannel, midiNote, gateTime, playback

    public var id: String { rawValue }
    public var layer: Int? {
        if rawValue.first == "a" { return 0 }
        if rawValue.first == "b" { return 1 }
        return nil
    }
    private var base: String { layer == nil ? rawValue : String(rawValue.dropFirst()) }
    public var offset: Int {
        let layerOffsets = ["Level": 6, "Pan": 7, "Decay": 8, "Pitch": 11, "Fine": 12,
                            "Cutoff": 13, "Filter": 14, "VelocityDecay": 15, "VelocityPitch": 16,
                            "VelocityFilter": 17, "VelocityVolume": 18, "VelocityMinimum": 19,
                            "VelocityMaximum": 20, "Loop": 21]
        if let layer { return layerOffsets[base]! + layer * 20 }
        return ["reverb": 44, "fx1": 45, "fx2": 61, "eqComp": 46, "priority": 48,
                "muteGroup": 49, "noteOff": 50, "midiChannel": 51, "midiNote": 52,
                "gateTime": 53, "playback": 54][base]!
    }
    public var title: String {
        ["Level": "Level", "Pan": "Pan", "Decay": "Decay", "Pitch": "Pitch", "Fine": "Fine pitch",
         "Cutoff": "Filter cutoff", "Filter": "Filter", "VelocityDecay": "Velocity → decay",
         "VelocityPitch": "Velocity → pitch", "VelocityFilter": "Velocity → filter",
         "VelocityVolume": "Velocity → volume", "VelocityMinimum": "Velocity minimum",
         "VelocityMaximum": "Velocity maximum", "Loop": "Loop", "reverb": "Reverb send",
         "fx1": "FX1 send", "fx2": "FX2 send", "eqComp": "EQ / compressor", "priority": "Priority",
         "muteGroup": "Mute group", "noteOff": "Note Off", "midiChannel": "MIDI channel",
         "midiNote": "MIDI note", "gateTime": "Gate time", "playback": "Playback"][base]!
    }
    public var range: ClosedRange<Int> {
        switch base {
        case "Pan", "Fine": return -50...50
        case "Pitch": return -12...12
        case "Decay", "Cutoff", "reverb", "fx1", "fx2": return 0...99
        case "Filter", "Loop", "eqComp", "playback": return 0...1
        case "priority", "noteOff": return 0...2
        case "muteGroup": return 0...9
        case "midiChannel": return 1...16
        case "gateTime": return 0...255 // 110...254 are rejected, never clamped.
        default: return 0...127
        }
    }
    public func accepts(_ value: Int) -> Bool {
        range.contains(value) && (self != .gateTime || value <= 109 || value == 255)
    }
    public func value(in pad: KitPad) -> Int {
        if self == .midiChannel { return pad.byte(offset) + 1 }
        return range.lowerBound < 0 ? pad.signed(offset) : pad.byte(offset)
    }
    public var options: [String]? {
        switch base {
        case "Filter", "Loop", "eqComp": return ["Off", "On"]
        case "priority": return ["Low", "Medium", "High"]
        case "noteOff": return ["Sent", "None", "Alt"]
        case "playback": return ["Mono", "Poly"]
        default: return nil
        }
    }
    public func display(_ value: Int) -> String {
        if !accepts(value) { return "Unknown (\(value))" }
        if let options { return options[value] }
        switch base {
        case "Pitch": return "\(value) st"
        case "Fine": return "\(value) cents"
        case "gateTime":
            if value == 255 { return "Off" }
            if value < 100 { return "\(value) ms" }
            return "Sync 1/" + ["32", "32T", "16", "16T", "8", "8T", "4", "4T", "2", "2T"][value - 100]
        default: return String(value)
        }
    }
    func encoded(_ value: Int) throws -> Data {
        guard accepts(value) else { throw SetlistError.invalid("\(title) is outside its supported range.") }
        let stored = self == .midiChannel ? value - 1 : value
        return Data([UInt8(truncatingIfNeeded: stored)])
    }
}

/// Memory-only editing of an imported copy. History stores at most 20 small byte patches.
public struct KitEditingSession: Sendable {
    public let originalData: Data
    public private(set) var current: KitInspection
    private struct Change: Sendable {
        let pad: Int; let offset: Int; let before: Data; let after: Data; let label: String
    }
    private var past: [Change] = []
    private var future: [Change] = []
    public var isDirty: Bool { current.originalData != originalData }
    public var undoLabel: String? { past.last?.label }
    public var redoLabel: String? { future.last?.label }
    public var undoCount: Int { past.count }

    public init(_ kit: KitInspection) {
        originalData = kit.originalData
        current = kit
    }

    public mutating func set(_ parameter: KitParameter, value: Int, pad: Int) throws {
        try check(pad)
        let bytes = try parameter.encoded(value)
        let zone = current.pads[pad]
        if parameter == .aVelocityMinimum && value > zone.byte(20) ||
           parameter == .aVelocityMaximum && value < zone.byte(19) ||
           parameter == .bVelocityMinimum && value > zone.byte(40) {
            throw SetlistError.invalid("Velocity minimum must not exceed velocity maximum.")
        }
        try apply(pad: pad, offset: parameter.offset, bytes: bytes,
                  label: "\(zone.label): \(parameter.layer.map { "Layer \($0 == 0 ? "A" : "B") " } ?? "")\(parameter.title)")
    }

    public mutating func assign(_ reference: Int, layer: Int, pad: Int) throws {
        try check(pad)
        guard (0...1).contains(layer), reference == 65535 || current.instruments.indices.contains(reference) else {
            throw SetlistError.invalid("Choose an existing kit reference or Unassigned.")
        }
        let bytes = Data([UInt8(reference & 255), UInt8(reference >> 8)])
        try apply(pad: pad, offset: layer == 0 ? 4 : 24, bytes: bytes,
                  label: "\(current.pads[pad].label): Layer \(layer == 0 ? "A" : "B") assignment")
    }

    private func check(_ pad: Int) throws {
        guard current.pads.indices.contains(pad) else { throw SetlistError.invalid("Choose a pad zone.") }
        if let issue = current.editingIssue { throw SetlistError.invalid(issue) }
        guard current.pads[pad].isKnownZone else { throw SetlistError.invalid("Editing this unknown zone is not supported.") }
    }
    private mutating func apply(pad: Int, offset: Int, bytes: Data, label: String) throws {
        let before = Data(current.pads[pad].payload[offset..<offset + bytes.count])
        guard before != bytes else { return }
        let candidate = try current.replacing(pad: pad, offset: offset, bytes: bytes)
        past.append(Change(pad: pad, offset: offset, before: before, after: bytes, label: label))
        if past.count > 20 { past.removeFirst() }
        future.removeAll()
        current = candidate
    }
    public mutating func undo() throws {
        guard let change = past.last else { return }
        let candidate = try current.replacing(pad: change.pad, offset: change.offset, bytes: change.before)
        past.removeLast(); future.append(change); current = candidate
    }
    public mutating func redo() throws {
        guard let change = future.last else { return }
        let candidate = try current.replacing(pad: change.pad, offset: change.offset, bytes: change.after)
        future.removeLast(); past.append(change); current = candidate
    }
}
