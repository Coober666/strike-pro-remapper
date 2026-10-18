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
        let model = MobileCompanionModel()
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
        let model = MobileCompanionModel()
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
        let model = MobileCompanionModel()
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
}
