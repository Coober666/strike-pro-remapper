import XCTest
import StrikeSetlists
@testable import StrikeCompanionMobile

final class CompanionTests: XCTestCase {
    struct FormatCase: Decodable { let name: String; let json: String; let valid: Bool }

    func testSharedPythonSwiftFormatCases() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "Cases", withExtension: "json"))
        let cases = try JSONDecoder().decode([FormatCase].self, from: Data(contentsOf: url))
        XCTAssertGreaterThanOrEqual(cases.count, 35)
        for item in cases {
            XCTAssertEqual((try? Setlist.decode(Data(item.json.utf8))) != nil, item.valid, item.name)
        }
    }

    @MainActor
    func testImportPreservesCurrentSongOnFailureAndNeverWritesSource() async throws {
        let model = MobileCompanionModel(store: nil)
        model.showDemo()
        let demo = try XCTUnwrap(model.session.document)
        model.select(1)
        let originalID = model.documentID
        model.query = "brushes"
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: folder) }
        let file = folder.appendingPathComponent("setlist.json")
        let invalid = Data("{broken".utf8)
        try invalid.write(to: file)
        await model.open(file)
        XCTAssertEqual(model.session.document, demo)
        XCTAssertEqual(model.session.selected, 1)
        XCTAssertEqual(model.documentID, originalID)
        XCTAssertEqual(model.query, "brushes")
        XCTAssertTrue(model.isDemo)
        XCTAssertNotNil(model.errorMessage)
        XCTAssertFalse(model.isLoading)
        XCTAssertEqual(try Data(contentsOf: file), invalid)
        let valid = Data(#"{"format":"strike-setlist","version":1,"name":"Imported show","numbered":false,"notes":"Show cue","entries":[{"kit":"Test.skt","song":"Opener","notes":"Count four"}]}"#.utf8)
        try valid.write(to: file)
        await model.open(file)
        XCTAssertEqual(model.session.document?.name, "Imported show")
        XCTAssertEqual(model.session.selected, 0)
        XCTAssertEqual(model.sourceName, "setlist.json")
        XCTAssertNotEqual(model.documentID, originalID)
        let firstImportID = model.documentID
        await model.open(file)
        XCTAssertNotEqual(model.documentID, firstImportID, "Reopening the same file also resets the reading pane")
        XCTAssertFalse(model.isDemo)
        XCTAssertEqual(model.query, "")
        XCTAssertNil(model.errorMessage)
        XCTAssertEqual(try Data(contentsOf: file), valid)
        try Data(repeating: 32, count: Setlist.maximumBytes + 1).write(to: file)
        await model.open(file)
        XCTAssertEqual(model.session.document?.name, "Imported show")
        await model.open(folder)
        XCTAssertEqual(model.session.document?.name, "Imported show")
        await model.open(folder.appendingPathComponent("missing.json"))
        XCTAssertEqual(model.session.document?.name, "Imported show")
        await model.open(URL(string: "https://example.invalid/setlist.json")!)
        XCTAssertEqual(model.session.document?.name, "Imported show")
        XCTAssertTrue(model.errorMessage?.contains("from Files") == true)
    }

    @MainActor
    func testNavigationIgnoresSearchAndClampsAtEnds() throws {
        let model = MobileCompanionModel(store: nil)
        model.showDemo()
        XCTAssertNotNil(model.session.document)
        model.move(-1)
        XCTAssertEqual(model.session.selected, 0)
        model.query = "Last Train"
        XCTAssertEqual(model.session.document?.matchingIndices(model.query), [2])
        model.move(1)
        XCTAssertEqual(model.session.selected, 1)
        model.select(3)
        model.move(1)
        XCTAssertEqual(model.session.selected, 3)
        model.select(-1)
        XCTAssertEqual(model.session.selected, 3)
        model.report(NSError(domain: NSCocoaErrorDomain, code: NSUserCancelledError))
        XCTAssertNil(model.errorMessage)
    }

    @MainActor
    func testEmptySetlistAndNewImportResetSelection() async throws {
        let model = MobileCompanionModel(store: nil)
        model.showDemo()
        model.select(2)
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        try Data(#"{"format":"strike-setlist","version":1,"name":"Empty","numbered":false,"entries":[]}"#.utf8).write(to: file)
        await model.open(file)
        XCTAssertNil(model.session.selected)
        model.move(1)
        model.select(0)
        XCTAssertNil(model.session.selected)
        model.showDemo()
        XCTAssertEqual(model.session.selected, 0)
    }
    @MainActor
    func testPersistenceRestoresImportedCopySongAndReadingOptions() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let store = CompanionSessionStore(url: folder.appendingPathComponent("saved/session.json"))
        let source = folder.appendingPathComponent("original.json")
        let demo = MobileCompanionModel(store: nil)
        demo.showDemo()
        let bytes = try CompanionSessionStore.documentData(XCTUnwrap(demo.session.document))
        try bytes.write(to: source)
        let model = MobileCompanionModel(store: store)
        await model.open(source)
        model.select(2)
        model.performanceMode = true
        model.noteScale = 1.6
        model.query = "temporary filter"
        let saved = try Data(contentsOf: store.url)
        try Data("invalid".utf8).write(to: source)
        await model.open(source)
        XCTAssertEqual(try Data(contentsOf: store.url), saved, "Failed imports must not replace the saved session")
        try FileManager.default.removeItem(at: source)
        let restored = MobileCompanionModel(store: store)
        XCTAssertEqual(restored.session.document, model.session.document)
        XCTAssertEqual(restored.session.selected, 2)
        XCTAssertEqual(restored.sourceName, "original.json")
        XCTAssertFalse(restored.isDemo)
        XCTAssertTrue(restored.performanceMode)
        XCTAssertEqual(restored.noteScale, 1.6)
        XCTAssertEqual(restored.query, "")
        XCTAssertNil(restored.persistenceWarning)
        restored.closeSetlist()
        let closed = MobileCompanionModel(store: store)
        XCTAssertNil(closed.session.document)
        XCTAssertTrue(closed.performanceMode)
        XCTAssertEqual(closed.noteScale, 1.6)
    }

    @MainActor
    func testCorruptUnsupportedAndOversizedSnapshotsDoNotRestore() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let store = CompanionSessionStore(url: folder.appendingPathComponent("session.json"))
        let model = MobileCompanionModel(store: store)
        model.showDemo()
        var snapshot = try XCTUnwrap(store.load())
        snapshot.selected = Int.max
        try store.save(snapshot)
        XCTAssertEqual(MobileCompanionModel(store: store).session.selected, 0)
        let good = try Data(contentsOf: store.url)
        snapshot.version = 2
        XCTAssertThrowsError(try store.save(snapshot))
        XCTAssertEqual(try Data(contentsOf: store.url), good)
        try JSONEncoder().encode(snapshot).write(to: store.url)
        for bad in [try Data(contentsOf: store.url), Data("broken".utf8),
                    Data(repeating: 32, count: CompanionSessionStore.maximumBytes + 1)] {
            try bad.write(to: store.url)
            let restored = MobileCompanionModel(store: store)
            XCTAssertNil(restored.session.document)
            XCTAssertNotNil(restored.persistenceWarning)
            XCTAssertFalse(restored.canRetryPersistence)
            XCTAssertEqual(try Data(contentsOf: store.url), bad, "Do not silently overwrite a failed restore")
        }
        snapshot.version = 1
        snapshot.document = Data("{}".utf8)
        try JSONEncoder().encode(snapshot).write(to: store.url)
        XCTAssertNil(MobileCompanionModel(store: store).session.document)
        XCTAssertThrowsError(try store.load())
    }

    @MainActor
    func testPersistenceFailureRetainsOpenWorkAndAllowsRetry() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let parent = folder.appendingPathComponent("blocked")
        try Data("file, not directory".utf8).write(to: parent)
        let store = CompanionSessionStore(url: parent.appendingPathComponent("session.json"))
        let model = MobileCompanionModel(store: store)
        model.showDemo()
        model.select(1)
        XCTAssertNotNil(model.session.document)
        XCTAssertNotNil(model.persistenceWarning)
        XCTAssertTrue(model.canRetryPersistence)
        try FileManager.default.removeItem(at: parent)
        model.persist()
        XCTAssertNil(model.persistenceWarning)
        XCTAssertFalse(model.canRetryPersistence)
        XCTAssertEqual(MobileCompanionModel(store: store).session.selected, 1)
    }

    struct KitCase: Decodable {
        struct Expected: Decodable {
            struct Pad: Decodable { let id: String; let a: Int; let b: Int; let payload: String; let level: Int; let pan: Int; let pitch: Int }
            let header: String; let tail: String; let instruments: [String]; let pads: [Pad]
        }
        let name: String; let data: Data; let expected: Expected?
    }

    func testKitInspectorPythonParityAndMalformedFiles() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "KitCases", withExtension: "json"))
        let cases = try JSONDecoder().decode([KitCase].self, from: Data(contentsOf: url))
        XCTAssertGreaterThanOrEqual(cases.count, 13)
        func hex(_ data: Data) -> String { data.map { String(format: "%02x", $0) }.joined() }
        for item in cases {
            guard let expected = item.expected else {
                XCTAssertThrowsError(try KitInspection.decode(item.data), item.name)
                continue
            }
            let kit = try KitInspection.decode(item.data)
            XCTAssertEqual(kit.originalData, item.data, item.name)
            XCTAssertEqual(hex(kit.header), expected.header)
            XCTAssertEqual(hex(kit.tail), expected.tail)
            XCTAssertEqual(kit.instruments, expected.instruments)
            XCTAssertEqual(kit.pads.count, expected.pads.count)
            for (pad, expected) in zip(kit.pads, expected.pads) {
                XCTAssertEqual(pad.id, expected.id)
                XCTAssertEqual(pad.layerA, expected.a)
                XCTAssertEqual(pad.layerB, expected.b)
                XCTAssertEqual(hex(pad.payload), expected.payload)
                XCTAssertEqual(pad.byte(6), expected.level)
                XCTAssertEqual(pad.signed(7), expected.pan)
                XCTAssertEqual(pad.signed(11), expected.pitch)
            }
            if item.name == "unknown-zone-unresolved-reference" {
                XCTAssertEqual(kit.pads[0].label, "ZZZ")
                XCTAssertEqual(kit.reference(42), "Unresolved string index 42")
                XCTAssertEqual(kit.reference(65535), "Unassigned")
                XCTAssertEqual(kit.unresolvedCount, 1)
            }
        }
        let complete = try XCTUnwrap(cases.first { $0.name == "complete" })
        let end = complete.data.count - (try KitInspection.decode(complete.data)).tail.count
        for count in 0..<end { XCTAssertThrowsError(try KitInspection.decode(complete.data.prefix(count)), "truncated at \(count)") }
        XCTAssertThrowsError(try KitInspection.decode(Data(repeating: 0, count: KitInspection.maximumBytes + 1)))
    }

    @MainActor
    func testKitImportsNeverWriteOrReplaceCurrentKitOnFailure() async throws {
        let model = KitInspectorModel()
        await model.demo()
        XCTAssertEqual(model.kit?.pads.count, 24)
        model.selected = 2
        let original = try XCTUnwrap(model.kit?.originalData)
        let id = model.documentID
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let source = folder.appendingPathComponent("kit.skt")
        let invalid = Data("broken".utf8)
        try invalid.write(to: source)
        await model.open(source)
        XCTAssertEqual(model.kit?.originalData, original)
        XCTAssertEqual(model.selected, 2)
        XCTAssertEqual(model.documentID, id)
        XCTAssertNotNil(model.errorMessage)
        XCTAssertEqual(try Data(contentsOf: source), invalid)
        await model.open(folder)
        await model.open(folder.appendingPathComponent("missing.skt"))
        await model.open(URL(string: "https://example.invalid/kit.skt")!)
        XCTAssertEqual(model.kit?.originalData, original)
        try original.write(to: source)
        await model.open(source)
        XCTAssertEqual(model.selected, 0)
        XCTAssertNotEqual(model.documentID, id)
        XCTAssertNil(model.errorMessage)
        XCTAssertEqual(try Data(contentsOf: source), original)
        try FileManager.default.removeItem(at: source)
        XCTAssertEqual(model.kit?.originalData, original, "Inspection owns bytes, never follows references")
    }

}
