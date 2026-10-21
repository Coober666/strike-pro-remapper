import Foundation

func trimmedMIDIText(_ value: String) -> String {
    // JavaScript trim also removes BOM; keep native exports valid in the web toolkit.
    value.trimmingCharacters(in: .whitespacesAndNewlines.union(CharacterSet(charactersIn: "\u{feff}")))
}

func boundedMIDIInputName(_ name: String) -> String {
    let clean = trimmedMIDIText(name)
    return String(decoding: (clean.isEmpty ? "Unnamed MIDI input" : clean).utf16.prefix(160), as: UTF16.self)
}

/// MIDI 1 channel messages only. No audio, output, device access or kit edits.
struct DrumMIDIMessage: Equatable, Sendable {
    let data: [UInt8]
    init?(_ data: [UInt8]) {
        guard let status = data.first, (0x80..<0xf0).contains(status),
              data.count == ([0xc, 0xd].contains(status >> 4) ? 2 : 3),
              data.dropFirst().allSatisfy({ $0 < 128 }) else { return nil }
        self.data = data
    }
    var channel: Int { Int(data[0] & 15) + 1 }
    var kind: UInt8 { data[0] >> 4 }
    var isHit: Bool { kind == 9 && data[2] > 0 }
    var isNoteOff: Bool { kind == 8 || (kind == 9 && data[2] == 0) }
    var label: String {
        if isHit { return "Note on" }
        if isNoteOff { return "Note off" }
        return [10: "Poly pressure", 11: "Control change", 12: "Program change",
                13: "Channel pressure", 14: "Pitch bend"][kind] ?? "Channel message"
    }
}

/// UMP messages are variable-width. Never mistake a SysEx/MIDI 2 payload word for a note.
enum DrumMIDIUMP {
    static let widths = [1, 1, 1, 2, 2, 4, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4]
    static func decode(_ words: UnsafeBufferPointer<UInt32>, receive: (DrumMIDIMessage) -> Void) -> Bool {
        var index = 0
        // Stop at unsupported data so the retained events form a prefix.
        while index < words.count {
            let word = words[index], type = Int(word >> 28), width = widths[type]
            guard index + width <= words.count else { return false }
            if type == 2 {
                // Session v1 has channel/note identity but no UMP group identity.
                guard (word >> 24) & 15 == 0 else { return false }
                let status = UInt8((word >> 16) & 255)
                let bytes = [status, UInt8((word >> 8) & 255)] +
                    ([0xc, 0xd].contains(status >> 4) ? [] : [UInt8(word & 255)])
                guard let message = DrumMIDIMessage(bytes) else { return false }
                receive(message)
            } else if type == 4 { return false }
            index += width
        }
        return true
    }
}

struct DrumMIDIEvent: Codable, Equatable, Sendable {
    let t: Double
    let data: [UInt8]
}
struct DrumMIDIPadName: Codable, Equatable, Sendable {
    let channel: Int
    let note: Int
    let label: String
}
struct DrumMIDIProfile: Encodable, Sendable {
    let format = "drum-midi-profile"
    let version = 1
    let name = "Learned pads"
    var mappings: [DrumMIDIPadName] = []
}
struct DrumMIDITake: Encodable, Sendable {
    static let maximumEvents = 50_000
    static let maximumDuration = 1_200_000.0
    static let maximumBytes = 8 * 1024 * 1024
    let format = "drum-midi-session"
    let version = 1
    let name = "Native MIDI capture"
    let source: String
    let createdAt: String
    let synthetic: Bool
    var durationMs = 0.0
    let segments = [0]
    var captureStatus = "complete"
    var events: [DrumMIDIEvent] = []
    var padMap = DrumMIDIProfile()

    init(source: String, synthetic: Bool = false) {
        self.source = boundedMIDIInputName(source)
        self.synthetic = synthetic
        createdAt = ISO8601DateFormatter().string(from: Date())
    }
    mutating func append(_ message: DrumMIDIMessage, milliseconds: Double) -> Bool {
        guard milliseconds.isFinite, milliseconds >= 0, events.count < Self.maximumEvents,
              milliseconds <= Self.maximumDuration else { return false }
        let t = max(events.last?.t ?? 0, milliseconds)
        events.append(DrumMIDIEvent(t: t, data: message.data))
        durationMs = max(durationMs, t)
        return true
    }
    mutating func finish(milliseconds: Double, partial: Bool) {
        if milliseconds.isFinite { durationMs = max(durationMs, min(Self.maximumDuration, max(0, milliseconds))) }
        if partial { captureStatus = "partial" }
    }
    mutating func namePad(channel: Int, note: Int, label: String) -> Bool {
        let clean = trimmedMIDIText(label)
        guard (1...16).contains(channel), (0...127).contains(note), !clean.isEmpty,
              clean.utf16.count <= 80, !clean.contains(where: { $0.isNewline || $0 == "\t" }) else { return false }
        let old = padMap.mappings.firstIndex { $0.channel == channel && $0.note == note }
        guard old != nil || padMap.mappings.count < 128 else { return false }
        let entry = DrumMIDIPadName(channel: channel, note: note, label: clean)
        if let old { padMap.mappings[old] = entry } else { padMap.mappings.append(entry) }
        padMap.mappings.sort { ($0.channel, $0.note) < ($1.channel, $1.note) }
        return true
    }
    func exported() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let bytes = try encoder.encode(self)
        guard bytes.count <= Self.maximumBytes else { throw CocoaError(.fileWriteOutOfSpace) }
        return bytes
    }
}

struct DrumMIDINoteSummary: Identifiable {
    var id: String { "\(channel):\(note)" }
    let channel: Int
    let note: Int
    var hits = 0
    var minimum = 127
    var maximum = 0
    var total = 0
    var mean: Double { hits == 0 ? 0 : Double(total) / Double(hits) }
}

/// Bounded handoff from Core MIDI's receive thread. Each recording owns a fresh mailbox.
/// No per-event Tasks, no unbounded dispatch queue, and late callbacks cannot enter a new take.
final class DrumMIDIMailbox: @unchecked Sendable {
    struct Entry: Sendable { let message: DrumMIDIMessage; let uptime: Double }
    private let lock = NSLock()
    private var entries: [Entry] = []
    private var accepting = true
    private var failed = false
    static let capacity = 4096
    func push(_ message: DrumMIDIMessage, uptime: Double) {
        lock.lock(); defer { lock.unlock() }
        guard accepting, !failed else { return }
        guard entries.count < Self.capacity else { failed = true; return }
        entries.append(Entry(message: message, uptime: uptime))
    }
    func fail() { lock.lock(); if accepting { failed = true }; lock.unlock() }
    func close() { lock.lock(); accepting = false; lock.unlock() }
    func drain() -> (entries: [Entry], failed: Bool) {
        lock.lock(); defer { lock.unlock() }
        let result = (entries, failed)
        entries.removeAll(keepingCapacity: true)
        return result
    }
}
