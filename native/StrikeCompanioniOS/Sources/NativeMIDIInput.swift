import Foundation
import CoreMIDI

struct NativeMIDIInput: Identifiable, Equatable {
    let id: Int32
    let name: String
}
@MainActor
protocol NativeMIDIInputDriver: AnyObject {
    var changed: (() -> Void)? { get set }
    var disconnected: (() -> Void)? { get set }
    var synthetic: Bool { get }
    func inputs() throws -> [NativeMIDIInput]
    func start(_ id: Int32, mailbox: DrumMIDIMailbox) throws
    func stop()
    func close()
}

extension NativeMIDIInputDriver { func close() { stop() } }

/// Input only: no destination enumeration, output port, virtual endpoint, or send API.
@MainActor
final class CoreMIDIInputDriver: NativeMIDIInputDriver {
    var changed: (() -> Void)?
    var disconnected: (() -> Void)?
    let synthetic = false
    private var client = MIDIClientRef()
    private var port = MIDIPortRef()
    private var endpoint = MIDIEndpointRef()
    private var mailbox: DrumMIDIMailbox?

    private func check(_ status: OSStatus) throws {
        guard status == noErr else {
            throw NSError(domain: "CoreMIDI", code: Int(status), userInfo:
                [NSLocalizedDescriptionKey: "MIDI input access failed (\(status)). Refresh inputs and choose the source again."])
        }
    }
    private func prepare() throws {
        guard client == 0 else { return }
        try check(MIDIClientCreateWithBlock("Strike Remapper input" as CFString, &client) { [weak self] notification in
            let removed: MIDIObjectRef? = notification.pointee.messageID == .msgObjectRemoved
                ? UnsafeRawPointer(notification).assumingMemoryBound(to: MIDIObjectAddRemoveNotification.self).pointee.child : nil
            Task { @MainActor [weak self] in
                guard let self else { return }
                if let removed, removed == self.endpoint { self.disconnected?() }
                else { self.changed?() }
            }
        })
    }
    private func identity(_ source: MIDIEndpointRef) -> Int32? {
        var id: Int32 = 0, offline: Int32 = 0
        guard source != 0, MIDIObjectGetIntegerProperty(source, kMIDIPropertyUniqueID, &id) == noErr else { return nil }
        _ = MIDIObjectGetIntegerProperty(source, kMIDIPropertyOffline, &offline)
        return offline == 0 ? id : nil
    }
    func inputs() throws -> [NativeMIDIInput] {
        try prepare()
        var result: [NativeMIDIInput] = []
        for index in 0..<MIDIGetNumberOfSources() {
            let source = MIDIGetSource(index)
            guard let id = identity(source), !result.contains(where: { $0.id == id }) else { continue }
            var value: Unmanaged<CFString>?
            let status = MIDIObjectGetStringProperty(source, kMIDIPropertyDisplayName, &value)
            let name = status == noErr ? value?.takeRetainedValue() as String? : nil
            result.append(NativeMIDIInput(id: id, name: boundedMIDIInputName(name ?? "Unnamed MIDI input")))
        }
        return result
    }
    func start(_ id: Int32, mailbox: DrumMIDIMailbox) throws {
        stop()
        try prepare()
        // Resolve stable source identity immediately before opening, never a saved list position.
        let matches = (0..<MIDIGetNumberOfSources()).map { MIDIGetSource($0) }.filter { identity($0) == id }
        guard matches.count == 1, let source = matches.first else {
            throw NSError(domain: "CoreMIDI", code: -1, userInfo:
                [NSLocalizedDescriptionKey: "The selected MIDI input is no longer available. Refresh and choose it again."])
        }
        self.mailbox = mailbox
        do {
            try check(MIDIInputPortCreateWithProtocol(client, "Strike Remapper receive" as CFString, ._1_0, &port) { list, _ in
                Self.receive(list, into: mailbox)
            })
            endpoint = source
            try check(MIDIPortConnectSource(port, source, nil))
            guard identity(source) == id else { throw CocoaError(.fileReadUnknown) }
        } catch { stop(); throw error }
    }
    nonisolated static func receive(_ list: UnsafePointer<MIDIEventList>, into mailbox: DrumMIDIMailbox) {
        // Walk the original variable-length list by pointer; copying packet tuples truncates large packets.
        guard list.pointee.numPackets <= DrumMIDIMailbox.capacity else { mailbox.fail(); return }
        let raw = UnsafeRawPointer(list).advanced(by: MemoryLayout<MIDIEventList>.offset(of: \.packet)!)
        var packet = raw.assumingMemoryBound(to: MIDIEventPacket.self)
        var remaining = DrumMIDIMailbox.capacity
        for _ in 0..<list.pointee.numPackets {
            let count = Int(packet.pointee.wordCount)
            guard count <= remaining else { mailbox.fail(); return }
            remaining -= count
            let words = UnsafeRawPointer(packet).advanced(by: MemoryLayout<MIDIEventPacket>.offset(of: \.words)!)
                .assumingMemoryBound(to: UInt32.self)
            let uptime = ProcessInfo.processInfo.systemUptime
            let supported = DrumMIDIUMP.decode(UnsafeBufferPointer(start: words, count: count)) {
                mailbox.push($0, uptime: uptime)
            }
            if !supported { mailbox.fail(); return }
            packet = UnsafePointer(MIDIEventPacketNext(packet))
        }
    }
    func stop() {
        mailbox?.close()
        mailbox = nil
        if port != 0 {
            if endpoint != 0 { _ = MIDIPortDisconnectSource(port, endpoint) }
            _ = MIDIPortDispose(port)
        }
        endpoint = 0; port = 0
    }
    func close() {
        stop()
        if client != 0 { _ = MIDIClientDispose(client); client = 0 }
    }
}

#if DEBUG
/// Only selected via both private UI-test environment flags; never creates a real MIDI endpoint.
@MainActor
final class SyntheticMIDIInputDriver: NativeMIDIInputDriver {
    var changed: (() -> Void)?
    var disconnected: (() -> Void)?
    let synthetic = true
    private var timer: Timer?
    private var mailbox: DrumMIDIMailbox?
    func inputs() throws -> [NativeMIDIInput] { [NativeMIDIInput(id: 1, name: "Synthetic drum input")] }
    func start(_ id: Int32, mailbox: DrumMIDIMailbox) throws {
        self.mailbox = mailbox
        timer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { _ in
            let now = ProcessInfo.processInfo.systemUptime
            for bytes: [UInt8] in [[0x99, 38, 96], [0x99, 38, 0], [0xb9, 4, 64]] {
                if let message = DrumMIDIMessage(bytes) { mailbox.push(message, uptime: now) }
            }
        }
    }
    func stop() { timer?.invalidate(); timer = nil; mailbox?.close(); mailbox = nil }
}
#endif
