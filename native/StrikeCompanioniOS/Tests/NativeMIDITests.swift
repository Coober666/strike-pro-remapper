import XCTest
import CoreMIDI
@testable import StrikeCompanionMobile

@MainActor
private final class FakeMIDIInput: NativeMIDIInputDriver {
    var changed: (() -> Void)?
    var disconnected: (() -> Void)?
    var failed: ((Int32) -> Void)?
    let synthetic = true
    var available = [NativeMIDIInput(id: 71, name: "Test drums")]
    var box: DrumMIDIMailbox?
    var opens = 0
    var stops = 0
    var failOpen = false
    func inputs() throws -> [NativeMIDIInput] { available }
    func start(_ id: Int32, mailbox: DrumMIDIMailbox) throws {
        opens += 1
        if failOpen { throw CocoaError(.fileReadUnknown) }
        box = mailbox
    }
    func stop() { stops += 1; box?.close() }
    func send(_ bytes: [UInt8], at time: Double) {
        if let message = DrumMIDIMessage(bytes) { box?.push(message, uptime: time) }
    }
}

final class NativeMIDITests: XCTestCase {
    func testDriverErrorNotificationSnapshotAndActiveDeviceRouting() {
        var notification = MIDIIOErrorNotification(messageID: .msgIOError,
            messageSize: UInt32(MemoryLayout<MIDIIOErrorNotification>.size), driverDevice: 7, errorCode: -50)
        let failure = withUnsafePointer(to: &notification) {
            NativeMIDIIOFailure.snapshot(UnsafeRawPointer($0).assumingMemoryBound(to: MIDINotification.self))
        }
        XCTAssertEqual(failure, NativeMIDIIOFailure(device: 7, code: -50))
        XCTAssertTrue(failure!.affects(endpoint: 1, device: 7))
        XCTAssertFalse(failure!.affects(endpoint: 1, device: 8), "An unrelated device must not stop the selected input")
        XCTAssertFalse(failure!.affects(endpoint: 0, device: 7), "A stopped input ignores later errors")
        XCTAssertTrue(failure!.affects(endpoint: 1, device: 0))
        var short = MIDINotification(messageID: .msgIOError, messageSize: UInt32(MemoryLayout<MIDINotification>.size))
        let unknown = withUnsafePointer(to: &short) { NativeMIDIIOFailure.snapshot($0) }
        XCTAssertEqual(unknown?.code, OSStatus(kMIDIUnknownError))
        XCTAssertTrue(unknown!.affects(endpoint: 1, device: 7))
        short.messageID = .msgSetupChanged
        XCTAssertNil(withUnsafePointer(to: &short) { NativeMIDIIOFailure.snapshot($0) })
    }
    func testCompleteChannelMessagesAndZeroVelocityNoteOff() {
        for channel: UInt8 in 0..<16 {
            for kind: UInt8 in 8..<15 {
                let bytes: [UInt8] = [kind << 4 | channel, 60] + ([12, 13].contains(kind) ? [] : [64])
                let message = DrumMIDIMessage(bytes)
                XCTAssertEqual(message?.channel, Int(channel) + 1)
                XCTAssertEqual(message?.kind, kind)
                XCTAssertNil(DrumMIDIMessage(bytes + [0]))
                XCTAssertNil(DrumMIDIMessage(Array(bytes.dropLast())))
            }
        }
        for bytes: [UInt8] in [[], [0x79, 60, 1], [0xf0, 60, 1], [0xf8], [0x90, 128, 1], [0x90, 60, 128]] {
            XCTAssertNil(DrumMIDIMessage(bytes))
        }
        XCTAssertTrue(DrumMIDIMessage([0x99, 38, 0])!.isNoteOff)
        XCTAssertFalse(DrumMIDIMessage([0x99, 38, 0])!.isHit)
    }
    func testUMPDoesNotTreatPayloadWordsAsNotesAndPreservesMessageLength() {
        var messages: [DrumMIDIMessage] = []
        let words: [UInt32] = [0x30900000, 0x20992660, // two-word SysEx, with a note-shaped payload
                               0x20992660, 0x20c90500, 0x20992600, 0x20b90440,
                               0x10f80000] // clock ignored
        XCTAssertTrue(words.withUnsafeBufferPointer { DrumMIDIUMP.decode($0) { messages.append($0) } })
        XCTAssertEqual(messages.map(\.data), [[0x99, 38, 96], [0xc9, 5], [0x99, 38, 0], [0xb9, 4, 64]])
        for bad: [UInt32] in [[0x30900000], [0x21992660], [0x40992660, 0], [0x20998060]] {
            XCTAssertFalse(bad.withUnsafeBufferPointer { DrumMIDIUMP.decode($0) { _ in XCTFail("Unsupported data became a note") } })
        }
        for unsupported: [UInt32] in [[0x21992660], [0x40992660, 0], [0x20998060]] {
            var prefix: [DrumMIDIMessage] = []
            let mixed = [0x20992660] + unsupported + [0x20992864]
            XCTAssertFalse(mixed.withUnsafeBufferPointer { DrumMIDIUMP.decode($0) { prefix.append($0) } })
            XCTAssertEqual(prefix.map(\.data), [[0x99, 38, 96]], "Never retain events beyond an unsupported gap")
        }
        // Native tuple declarations have only 64 words; the decoder must accept a larger buffer intact.
        let many = [UInt32](repeating: 0x20992660, count: 200)
        var count = 0
        XCTAssertTrue(many.withUnsafeBufferPointer { DrumMIDIUMP.decode($0) { _ in count += 1 } })
        XCTAssertEqual(count, 200)
    }
    func testActualVariableLengthCoreMIDIListsAcrossLargeAndMultiplePackets() throws {
        let storage = UnsafeMutableRawPointer.allocate(byteCount: 8192, alignment: MemoryLayout<MIDIEventList>.alignment)
        defer { storage.deallocate() }
        let list = storage.bindMemory(to: MIDIEventList.self, capacity: 1)
        var packet = MIDIEventListInit(list, ._1_0)
        let first = [UInt32](repeating: 0x20992660, count: 200)
        packet = first.withUnsafeBufferPointer { MIDIEventListAdd(list, 8192, packet, 1, $0.count, $0.baseAddress!) }
        XCTAssertNotNil(packet)
        let second: [UInt32] = [0x20892600, 0x20b90440]
        packet = second.withUnsafeBufferPointer { MIDIEventListAdd(list, 8192, packet, 2, $0.count, $0.baseAddress!) }
        XCTAssertNotNil(packet)
        let box = DrumMIDIMailbox()
        CoreMIDIInputDriver.receive(UnsafePointer(list), into: box)
        let result = box.drain()
        XCTAssertFalse(result.failed)
        XCTAssertEqual(result.entries.count, 202)
        XCTAssertEqual(result.entries.last?.message.data, [0xb9, 4, 64])
        XCTAssertEqual(result.entries[200].message.data, [0x89, 38, 0])
    }
    func testMailboxBoundAndClosedMailboxCannotLeakIntoAnotherRecording() {
        let box = DrumMIDIMailbox(), message = DrumMIDIMessage([0x99, 38, 96])!
        for _ in 0...DrumMIDIMailbox.capacity { box.push(message, uptime: 1) }
        let result = box.drain()
        XCTAssertEqual(result.entries.count, DrumMIDIMailbox.capacity)
        XCTAssertTrue(result.failed)
        box.close(); box.push(message, uptime: 2)
        XCTAssertTrue(box.drain().entries.isEmpty)
        let fresh = DrumMIDIMailbox()
        XCTAssertFalse(fresh.drain().failed)
        XCTAssertTrue(fresh.drain().entries.isEmpty)
    }
    func testTakeBoundsNamesAndPortableJSON() throws {
        var take = DrumMIDITake(source: String(repeating: "🥁", count: 200), synthetic: true)
        let hit = DrumMIDIMessage([0x99, 38, 96])!
        XCTAssertFalse(take.append(hit, milliseconds: .nan))
        XCTAssertFalse(take.append(hit, milliseconds: -1))
        XCTAssertFalse(take.append(hit, milliseconds: DrumMIDITake.maximumDuration + 1))
        XCTAssertTrue(take.append(hit, milliseconds: 50))
        XCTAssertTrue(take.append(hit, milliseconds: 40))
        XCTAssertEqual(take.events.map(\.t), [50, 50])
        XCTAssertFalse(take.namePad(channel: 0, note: 38, label: "Snare"))
        XCTAssertFalse(take.namePad(channel: 10, note: 128, label: "Snare"))
        XCTAssertFalse(take.namePad(channel: 10, note: 38, label: "\t"))
        XCTAssertFalse(take.namePad(channel: 10, note: 38, label: "\u{feff}"))
        XCTAssertEqual(boundedMIDIInputName("\u{feff} \n"), "Unnamed MIDI input")
        XCTAssertFalse(take.namePad(channel: 10, note: 38, label: String(repeating: "🥁", count: 41)))
        XCTAssertTrue(take.namePad(channel: 10, note: 38, label: " Snare "))
        XCTAssertTrue(take.namePad(channel: 1, note: 38, label: "Other channel"))
        XCTAssertTrue(take.namePad(channel: 10, note: 38, label: "Rim"))
        XCTAssertEqual(take.padMap.mappings.count, 2)
        take.finish(milliseconds: 75, partial: true)
        take.finish(milliseconds: 80, partial: false)
        let data = try take.exported()
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(json["format"] as? String, "drum-midi-session")
        XCTAssertEqual(json["captureStatus"] as? String, "partial")
        XCTAssertEqual(json["synthetic"] as? Bool, true)
        XCTAssertLessThanOrEqual((json["source"] as? String)?.utf16.count ?? 999, 160)
        XCTAssertEqual(json["segments"] as? [Int], [0])
        XCTAssertEqual(take.durationMs, 80)
        XCTAssertLessThan(data.count, DrumMIDITake.maximumBytes)
        for _ in take.events.count..<DrumMIDITake.maximumEvents { XCTAssertTrue(take.append(hit, milliseconds: 80)) }
        XCTAssertFalse(take.append(hit, milliseconds: 80))
        XCTAssertLessThan(try take.exported().count, DrumMIDITake.maximumBytes)
    }
    @MainActor
    func testExplicitStartStopDrainChannelIdentityAndCompletedTakeRetention() throws {
        var time = 100.0
        let driver = FakeMIDIInput()
        let model = NativeMIDIModel(driver: driver, clock: { time }, usesTimer: false)
        XCTAssertEqual(driver.opens, 0)
        model.refresh()
        XCTAssertNil(model.selectedInput, "Never auto-select a source")
        model.record()
        XCTAssertEqual(driver.opens, 0)
        model.selectedInput = 71; model.record()
        XCTAssertEqual(driver.opens, 1)
        driver.send([0x99, 38, 96], at: 100.1)
        driver.send([0x99, 38, 0], at: 100.2)
        driver.send([0x90, 38, 32], at: 100.3)
        driver.send([0xb9, 4, 64], at: 100.4)
        time = 101
        model.stop() // Must drain received data even without a timer tick.
        XCTAssertEqual(model.take?.events.count, 4)
        XCTAssertEqual(model.notes.count, 2)
        XCTAssertEqual(model.notes.map(\.hits), [1, 1])
        XCTAssertEqual(model.hiHat[10], 64)
        XCTAssertEqual(model.take?.durationMs, 1000)
        XCTAssertEqual(model.take?.captureStatus, "complete")
        let oldData = try model.exported()
        driver.available = []; driver.changed?(); model.background(); driver.failed?(-50)
        XCTAssertEqual(try model.exported(), oldData, "Disconnect/background after Stop cannot downgrade a complete take")
        XCTAssertNil(model.errorMessage, "A stopped take ignores later driver errors")
        model.record()
        XCTAssertEqual(driver.opens, 1, "Retained work requires explicit discard")
    }
    @MainActor
    func testBackgroundDisconnectOverflowAndIdleDurationRetainPartialWithoutReopening() throws {
        for failure in ["background", "disconnect", "removed-and-returned", "driver", "overflow", "events", "duration"] {
            var time = 1.0
            let driver = FakeMIDIInput()
            let subject = NativeMIDIModel(driver: driver, clock: { time }, usesTimer: false)
            subject.refresh(); subject.selectedInput = 71; subject.record()
            driver.send([0x99, 38, 96], at: 1.01)
            time = 2
            switch failure {
            case "background": subject.background()
            case "disconnect": driver.available = []; driver.changed?()
            case "removed-and-returned": driver.disconnected?()
            case "driver": driver.failed?(-50)
            case "overflow": driver.box?.fail(); subject.poll()
            case "events":
                subject.poll()
                while subject.isRecording && subject.take!.events.count < DrumMIDITake.maximumEvents {
                    let count = min(DrumMIDIMailbox.capacity, DrumMIDITake.maximumEvents - subject.take!.events.count)
                    for _ in 0..<count { driver.send([0x99, 38, 96], at: 1.01) }
                    subject.poll()
                }
            default: time = 1202; subject.poll()
            }
            XCTAssertFalse(subject.isRecording, failure)
            XCTAssertEqual(subject.take?.events.count, failure == "events" ? DrumMIDITake.maximumEvents : 1, failure)
            XCTAssertEqual(subject.take?.captureStatus, "partial", failure)
            XCTAssertLessThanOrEqual(subject.take!.durationMs, DrumMIDITake.maximumDuration)
            XCTAssertNoThrow(try subject.exported())
            if failure == "driver" { XCTAssertTrue(subject.errorMessage?.contains("-50") == true) }
            driver.available = [NativeMIDIInput(id: 71, name: "Returned")]; driver.changed?()
            XCTAssertEqual(driver.opens, 1, "No automatic reconnect")
        }
    }
    @MainActor
    func testLearnConsumesOnlyNewPositiveHitsAndApplyNeverEditsKit() throws {
        var time = 5.0
        let driver = FakeMIDIInput()
        let model = NativeMIDIModel(driver: driver, clock: { time }, usesTimer: false)
        model.refresh(); model.selectedInput = 71; model.record()
        driver.send([0x99, 38, 96], at: 5.01)
        time = 6; model.armLearn()
        XCTAssertNil(model.candidate)
        driver.send([0x99, 42, 100], at: 5.5) // A delayed callback with an old arrival time.
        driver.send([0x99, 44, 0], at: 6.01)
        driver.send([0xb9, 4, 127], at: 6.02)
        model.poll()
        XCTAssertNil(model.candidate)
        driver.send([0x99, 40, 92], at: 6.03)
        driver.send([0x99, 41, 100], at: 6.04)
        time = 7; model.poll()
        XCTAssertEqual(model.candidate?.data, [0x99, 40, 92], "Freeze the first candidate for confirmation")
        XCTAssertTrue(model.take!.padMap.mappings.isEmpty)
        model.applyName("\n")
        XCTAssertNotNil(model.errorMessage)
        XCTAssertTrue(model.learning)
        model.applyName("Snare rim")
        XCTAssertEqual(model.take?.padMap.mappings, [DrumMIDIPadName(channel: 10, note: 40, label: "Snare rim")])
        XCTAssertFalse(model.learning)
        model.armLearn(); model.cancelLearn()
        XCTAssertNil(model.candidate)
        model.stop(); model.armLearn()
        XCTAssertFalse(model.learning)
    }
    @MainActor
    func testFailedReplacementPreservesTakeAndStaleCallbacksCannotEnterNewTake() throws {
        let driver = FakeMIDIInput()
        let model = NativeMIDIModel(driver: driver, clock: { 10 }, usesTimer: false)
        model.refresh(); model.selectedInput = 71; model.record()
        driver.send([0x99, 38, 96], at: 10)
        let old = driver.box
        model.stop()
        let saved = try model.exported()
        driver.failOpen = true
        model.record(discardCurrent: true)
        XCTAssertEqual(try model.exported(), saved)
        XCTAssertFalse(model.isRecording)
        driver.failOpen = false
        model.record(discardCurrent: true)
        old?.push(DrumMIDIMessage([0x99, 42, 100])!, uptime: 10)
        model.poll()
        XCTAssertTrue(model.take!.events.isEmpty)
        XCTAssertNil(model.candidate)
        model.stop()
    }
}
