import XCTest
import SwiftUI
import UIKit
import StrikeSetlists
@testable import StrikeCompanionMobile

final class KitEditingTests: XCTestCase {
    struct Oracle: Decodable {
        struct Case: Decodable { let parameter: String?; let layer: Int?; let value: Int; let expected: Data? }
        let source: Data; let cases: [Case]
    }
    private func oracle() throws -> Oracle {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "KitEditingCases", withExtension: "json"))
        return try JSONDecoder().decode(Oracle.self, from: Data(contentsOf: url))
    }
    private func folder() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false)
        return url
    }
    func testEveryConfirmedFieldMatchesPythonWriterAndRejectsInvalidWithoutMutation() throws {
        let oracle = try oracle()
        let imported = try KitInspection.decode(oracle.source)
        XCTAssertEqual(imported.encoded(), oracle.source)
        XCTAssertEqual(Set(oracle.cases.compactMap(\.parameter)), Set(KitParameter.allCases.map(\.rawValue)))
        for item in oracle.cases {
            var session = KitEditingSession(imported)
            func edit(_ session: inout KitEditingSession) throws {
                if let name = item.parameter, let parameter = KitParameter(rawValue: name) { try session.set(parameter, value: item.value, pad: 2) }
                else { try session.assign(item.value, layer: item.layer!, pad: 2) }
            }
            guard let expected = item.expected else {
                XCTAssertThrowsError(try edit(&session), "\(item.parameter ?? "assignment") \(item.value)")
                XCTAssertEqual(session.current.encoded(), oracle.source)
                XCTAssertNil(session.undoLabel)
                XCTAssertFalse(session.isDirty)
                continue
            }
            try edit(&session)
            XCTAssertEqual(session.current.encoded(), expected, "\(item.parameter ?? "assignment") \(item.value)")
            XCTAssertEqual(session.originalData, oracle.source)
            XCTAssertEqual(session.current.header, imported.header)
            XCTAssertEqual(session.current.tail, imported.tail)
            XCTAssertEqual(session.current.instruments, imported.instruments)
            let roundtrip = try KitInspection.decode(session.current.encoded())
            XCTAssertEqual(roundtrip.encoded(), expected)
            try session.undo()
            XCTAssertEqual(session.current.encoded(), oracle.source)
            XCTAssertFalse(session.isDirty)
            try session.redo()
            XCTAssertEqual(session.current.encoded(), expected)
        }
    }
    func testVariableChunksAndSixteenBitAssignmentPreserveEveryOtherByte() throws {
        let imported = try KitInspection.decode(oracle().source)
        func block(_ magic: String, _ payload: Data) -> Data {
            let count = payload.count
            return Data(magic.utf8) + Data((0..<4).map { UInt8((count >> ($0 * 8)) & 255) }) + payload
        }
        let header = block("KIT ", Data((0..<4096).map { UInt8($0 % 256) }))
        var extended = imported.pads[0].payload
        extended.append(Data(repeating: 173, count: 4096 - extended.count))
        let short = Data(imported.pads[1].payload.prefix(62))
        let strings = (0..<4096).reduce(into: Data()) { $0.append(contentsOf: "Synthetic/Reference-\($1).sin\0".utf8) }
        let source = header + block("inst", extended) + block("inst", short) + block("str ", strings) + imported.tail
        var session = KitEditingSession(try KitInspection.decode(source))
        XCTAssertEqual(session.current.encoded(), source)
        try session.assign(300, layer: 1, pad: 1)
        XCTAssertEqual(session.current.pads[1].layerB, 300)
        XCTAssertEqual(session.current.pads[1].byte(24), 44)
        XCTAssertEqual(session.current.pads[1].byte(25), 1)
        let changed = session.current.encoded()
        let offsets = [header.count + 8 + extended.count + 8 + 24, header.count + 8 + extended.count + 8 + 25]
        XCTAssertTrue(zip(source, changed).enumerated().allSatisfy { offsets.contains($0.offset) || $0.element.0 == $0.element.1 })
        try session.set(.fx2, value: 99, pad: 1)
        XCTAssertEqual(session.current.pads[1].byte(61), 99)
        XCTAssertEqual(session.current.header, header)
        XCTAssertEqual(session.current.pads[0].payload, extended)
        XCTAssertEqual(session.current.tail, imported.tail)
        try session.undo(); try session.undo()
        XCTAssertEqual(session.current.encoded(), source)
    }
    func testHistoryNoOpsBranchingLimitsAndVelocityConsistency() throws {
        let original = try KitInspection.decode(oracle().source)
        var session = KitEditingSession(original)
        try session.set(.aLevel, value: original.pads[2].byte(6), pad: 2)
        XCTAssertNil(session.undoLabel)
        for value in 0..<25 { try session.set(.aLevel, value: value, pad: 2) }
        XCTAssertEqual(session.undoCount, 20)
        for _ in 0..<20 { try session.undo() }
        XCTAssertEqual(session.current.pads[2].byte(6), 4)
        XCTAssertNotNil(session.redoLabel)
        try session.set(.aLevel, value: 4, pad: 2)
        XCTAssertNotNil(session.redoLabel, "No-op edits cannot erase redo")
        XCTAssertThrowsError(try session.set(.aLevel, value: 128, pad: 2))
        XCTAssertNotNil(session.redoLabel, "Invalid edits cannot erase redo")
        try session.set(.aPan, value: -20, pad: 2)
        XCTAssertNil(session.redoLabel)
        try session.set(.aVelocityMinimum, value: 80, pad: 2)
        let before = session.current.encoded()
        let count = session.undoCount
        XCTAssertThrowsError(try session.set(.aVelocityMaximum, value: 79, pad: 2))
        XCTAssertEqual(session.current.encoded(), before)
        XCTAssertEqual(session.undoCount, count)
        XCTAssertThrowsError(try session.assign(0, layer: 2, pad: 2))
        XCTAssertThrowsError(try session.assign(0, layer: 0, pad: -1))
        XCTAssertThrowsError(try session.set(.aLevel, value: 0, pad: 128))
    }
    func testUnknownValuesAndNoncanonicalStringsRemainLosslessAndUnchangedUntilExplicitEdit() throws {
        let source = try oracle().source
        let parsed = try KitInspection.decode(source)
        var unknownValue = source
        unknownValue[parsed.header.count + 8 + 6] = 255
        var session = KitEditingSession(try KitInspection.decode(unknownValue))
        XCTAssertEqual(session.current.encoded(), unknownValue)
        try session.set(.aPan, value: 0, pad: 0)
        XCTAssertEqual(session.current.pads[0].byte(6), 255)
        try session.set(.aLevel, value: 127, pad: 0)
        XCTAssertEqual(session.current.pads[0].byte(6), 127)
        try session.undo()
        XCTAssertEqual(session.current.pads[0].byte(6), 255)
        XCTAssertEqual(KitParameter.aLevel.display(255), "Unknown (255)")
        let strings = parsed.instruments.reduce(into: Data()) { $0.append(contentsOf: $1.utf8); $0.append(0) }
        let stringStart = source.count - parsed.tail.count - strings.count - 8
        var padded = source
        padded.insert(0, at: stringStart + 8)
        var size = UInt32(strings.count + 1).littleEndian
        withUnsafeBytes(of: &size) { padded.replaceSubrange(stringStart + 4..<stringStart + 8, with: $0) }
        let noncanonical = try KitInspection.decode(padded)
        XCTAssertEqual(noncanonical.encoded(), padded)
        XCTAssertNotNil(noncanonical.editingIssue)
        session = KitEditingSession(noncanonical)
        XCTAssertThrowsError(try session.set(.aLevel, value: 10, pad: 0))
        XCTAssertEqual(session.current.encoded(), padded)
        var unknown = source
        unknown.replaceSubrange(parsed.header.count + 8..<parsed.header.count + 12, with: Data("ZZZ ".utf8))
        session = KitEditingSession(try KitInspection.decode(unknown))
        XCTAssertThrowsError(try session.set(.aLevel, value: 10, pad: 0))
        XCTAssertEqual(session.current.encoded(), unknown)
        var duplicate = source
        duplicate.replaceSubrange(parsed.header.count + 72 + 8..<parsed.header.count + 72 + 12,
                                  with: source[parsed.header.count + 8..<parsed.header.count + 12])
        session = KitEditingSession(try KitInspection.decode(duplicate))
        XCTAssertNotNil(session.current.editingIssue)
        XCTAssertThrowsError(try session.assign(0, layer: 0, pad: 2))
    }
    func testImportAndExportNeverAskOtherPresentersToSaveOriginals() throws {
        let directory = try folder()
        defer { try? FileManager.default.removeItem(at: directory) }
        let source = directory.appendingPathComponent("original.skt")
        let data = try oracle().source
        try data.write(to: source)
        let sourcePresenter = SaveObserver(url: source)
        let folderPresenter = SaveObserver(url: directory)
        NSFileCoordinator.addFilePresenter(sourcePresenter)
        NSFileCoordinator.addFilePresenter(folderPresenter)
        defer {
            NSFileCoordinator.removeFilePresenter(sourcePresenter)
            NSFileCoordinator.removeFilePresenter(folderPresenter)
        }
        XCTAssertEqual(try KitInspection.read(source).encoded(), data)
        XCTAssertEqual(sourcePresenter.saveRequests, 0, "An import must not ask another app to save the source")
        let copy = try KitCopyExporter.copy(data, to: directory)
        XCTAssertEqual(try Data(contentsOf: copy), data)
        XCTAssertEqual(try Data(contentsOf: source), data)
        XCTAssertEqual(sourcePresenter.saveRequests, 0)
        XCTAssertEqual(folderPresenter.saveRequests, 0, "Creating a new file must not request unrelated saves")
    }
    func testExportCreatesVerifiedCopyNeverOverwritesOriginalOrLinksAndCleansPartialFailures() throws {
        let directory = try folder()
        defer { try? FileManager.default.removeItem(at: directory) }
        let source = directory.appendingPathComponent("original.skt")
        let data = try oracle().source
        try data.write(to: source)
        var session = KitEditingSession(try KitInspection.read(source))
        try session.set(.aLevel, value: 73, pad: 2)
        try session.assign(6, layer: 1, pad: 2)
        let edited = session.current.encoded()
        let copy = try KitCopyExporter.copy(edited, to: directory)
        XCTAssertNotEqual(copy, source)
        XCTAssertEqual(try Data(contentsOf: source), data)
        let reopened = try KitInspection.read(copy)
        XCTAssertEqual(reopened.encoded(), edited)
        XCTAssertEqual(reopened.pads[2].byte(6), 73)
        XCTAssertEqual(reopened.pads[2].layerB, 6)
        XCTAssertThrowsError(try KitCopyExporter.create(data, in: directory, name: copy.lastPathComponent))
        XCTAssertEqual(try Data(contentsOf: copy), edited)
        let link = directory.appendingPathComponent("Kit-edit-12345678.skt")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: source)
        XCTAssertThrowsError(try KitCopyExporter.create(edited, in: directory, name: link.lastPathComponent))
        XCTAssertEqual(try Data(contentsOf: source), data)
        let failedName = "Kit-edit-00000000.skt"
        XCTAssertThrowsError(try KitCopyExporter.create(edited, in: directory, name: failedName) { file, bytes in
            try file.write(contentsOf: bytes.prefix(20))
            throw NSError(domain: NSPOSIXErrorDomain, code: 28) // deterministic disk-full fault
        })
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.appendingPathComponent(failedName).path))
        XCTAssertThrowsError(try KitCopyExporter.create(edited, in: directory, name: failedName) { file, _ in
            try file.write(contentsOf: Data("truncated".utf8))
        })
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.appendingPathComponent(failedName).path))
        let replacedName = "Kit-edit-11111111.skt"
        let replacement = directory.appendingPathComponent(replacedName)
        let other = Data("another process's file".utf8)
        XCTAssertThrowsError(try KitCopyExporter.create(edited, in: directory, name: replacedName) { file, bytes in
            try file.write(contentsOf: bytes)
            try FileManager.default.removeItem(at: replacement)
            try other.write(to: replacement)
        })
        XCTAssertEqual(try Data(contentsOf: replacement), other, "Never remove another process's replacement")
        XCTAssertThrowsError(try KitCopyExporter.create(edited, in: directory, name: "original.skt"))
        XCTAssertThrowsError(try KitCopyExporter.create(edited, in: source))
        XCTAssertThrowsError(try KitCopyExporter.create(Data("bad".utf8), in: directory))
        let directoryLink = directory.appendingPathComponent("linked-folder")
        try FileManager.default.createSymbolicLink(at: directoryLink, withDestinationURL: directory)
        XCTAssertThrowsError(try KitCopyExporter.create(edited, in: directoryLink))
        XCTAssertEqual(try Data(contentsOf: source), data)
    }
    @MainActor
    func testPendingReplacementPresentsOnEditorMountAndRetainsEditsUntilDecision() async throws {
        let model = KitInspectorModel()
        let directory = try folder()
        defer { try? FileManager.default.removeItem(at: directory) }
        let source = directory.appendingPathComponent("original.skt")
        let original = try oracle().source
        try original.write(to: source)
        await model.open(source)
        model.selected = 2
        XCTAssertTrue(model.edit(.aLevel, value: 74, pad: 2))
        let edited = try XCTUnwrap(model.kit?.encoded())
        let id = model.documentID
        let undo = model.session?.undoLabel
        // External Open In can finish before the full-screen editor is mounted.
        await model.open(source)
        XCTAssertNotNil(model.pendingImport)
        XCTAssertTrue(model.busy)

        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let previousKeyWindow = scene.windows.first(where: \.isKeyWindow)
        let window = UIWindow(windowScene: scene)
        let host = UIHostingController(rootView: KitInspectorView(model: model, close: {}))
        window.rootViewController = host
        window.makeKeyAndVisible()
        defer {
            host.dismiss(animated: false)
            window.isHidden = true
            window.rootViewController = nil
            previousKeyWindow?.makeKey()
        }
        func replacementAlert(_ controller: UIViewController) -> UIAlertController? {
            if let alert = controller as? UIAlertController, alert.title == "Replace the edited kit?" { return alert }
            if let presented = controller.presentedViewController, let alert = replacementAlert(presented) { return alert }
            return controller.children.lazy.compactMap { replacementAlert($0) }.first
        }
        let presented = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            replacementAlert(host) != nil
        }, object: nil)
        await fulfillment(of: [presented], timeout: 5)
        let alert = try XCTUnwrap(replacementAlert(host))
        XCTAssertEqual(Set(alert.actions.compactMap(\.title)), ["Discard edits and open kit", "Keep editing"])
        XCTAssertEqual(model.kit?.encoded(), edited)
        XCTAssertEqual(model.documentID, id)
        XCTAssertEqual(model.selected, 2)
        XCTAssertEqual(model.session?.undoLabel, undo)
        model.cancelReplacement()
        let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            replacementAlert(host) == nil
        }, object: nil)
        await fulfillment(of: [dismissed], timeout: 5)
        XCTAssertFalse(model.busy)
        XCTAssertEqual(model.kit?.encoded(), edited)
        XCTAssertTrue(model.isDirty)
        XCTAssertEqual(model.session?.undoLabel, undo)
        XCTAssertEqual(try Data(contentsOf: source), original)
    }

    @MainActor
    func testModelProtectsDirtyImportFailureCancelReplacementAndExportFailure() async throws {
        let model = KitInspectorModel()
        let directory = try folder()
        defer { try? FileManager.default.removeItem(at: directory) }
        let source = directory.appendingPathComponent("original.skt")
        let data = try oracle().source
        try data.write(to: source)
        await model.open(source)
        let id = model.documentID
        model.selected = 2
        XCTAssertTrue(model.edit(.aLevel, value: 74, pad: 2))
        let edited = try XCTUnwrap(model.kit?.encoded())
        let bad = directory.appendingPathComponent("bad.skt")
        try Data("bad".utf8).write(to: bad)
        await model.open(bad)
        XCTAssertEqual(model.kit?.encoded(), edited)
        XCTAssertEqual(model.documentID, id)
        XCTAssertEqual(model.selected, 2)
        XCTAssertNil(model.pendingImport)
        XCTAssertNotNil(model.session?.undoLabel)
        await model.open(source)
        XCTAssertNotNil(model.pendingImport)
        XCTAssertEqual(model.kit?.encoded(), edited)
        model.cancelReplacement()
        XCTAssertEqual(model.kit?.encoded(), edited)
        await model.export(to: source) // not a directory
        XCTAssertEqual(model.kit?.encoded(), edited)
        XCTAssertTrue(model.isDirty)
        XCTAssertNotNil(model.errorMessage)
        XCTAssertFalse(model.isExporting)
        model.errorMessage = nil
        await model.export(to: directory)
        XCTAssertNotNil(model.exportMessage)
        XCTAssertTrue(model.isDirty, "Export never changes the imported original or clears undo")
        XCTAssertNotNil(model.session?.undoLabel)
        let copies = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.hasPrefix("Kit-edit-") }
        XCTAssertEqual(copies.count, 1)
        XCTAssertEqual(try KitInspection.read(copies[0]).encoded(), edited)
        XCTAssertEqual(try Data(contentsOf: source), data)
        let successMessage = model.exportMessage
        let undoLabel = model.session?.undoLabel
        model.reportExportFailure(NSError(domain: NSCocoaErrorDomain, code: NSUserCancelledError))
        XCTAssertEqual(model.exportMessage, successMessage, "Cancelling the folder picker is not an export failure")
        XCTAssertNil(model.errorMessage)
        model.reportExportFailure(NSError(domain: NSCocoaErrorDomain, code: NSFileReadNoPermissionError))
        XCTAssertEqual(model.errorTitle, "Copy couldn’t be exported")
        XCTAssertTrue(model.errorMessage?.contains("Your edits are still open") == true)
        XCTAssertTrue(model.errorMessage?.contains("Check the destination") == true)
        XCTAssertNil(model.exportMessage, "A provider error must clear stale export success")
        XCTAssertEqual(model.kit?.encoded(), edited)
        XCTAssertTrue(model.isDirty)
        XCTAssertEqual(model.session?.undoLabel, undoLabel)
        XCTAssertEqual(model.documentID, id)
        XCTAssertEqual(model.selected, 2)
        XCTAssertEqual(try Data(contentsOf: source), data)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.hasPrefix("Kit-edit-") }.count, 1, "Reporting an error must never retry export")
        model.errorMessage = nil
        model.report(NSError(domain: NSCocoaErrorDomain, code: NSFileReadNoPermissionError))
        XCTAssertEqual(model.errorTitle, "Kit couldn’t be opened", "Import errors retain their own guidance")
        model.undo()
        XCTAssertFalse(model.isDirty)
        model.redo()
        XCTAssertTrue(model.isDirty)
        await model.open(source)
        model.confirmReplacement()
        XCTAssertFalse(model.isDirty)
        XCTAssertNil(model.session?.undoLabel)
        XCTAssertNotEqual(model.documentID, id)
        XCTAssertEqual(model.selected, 0)
        XCTAssertEqual(try Data(contentsOf: source), data)
    }
}


private final class SaveObserver: NSObject, NSFilePresenter, @unchecked Sendable {
    let presentedItemURL: URL?
    let presentedItemOperationQueue = OperationQueue()
    private let lock = NSLock()
    private var count = 0
    var saveRequests: Int { lock.lock(); defer { lock.unlock() }; return count }
    init(url: URL) { presentedItemURL = url; super.init() }
    func savePresentedItemChanges(completionHandler: @escaping @Sendable (Error?) -> Void) {
        lock.lock(); count += 1; lock.unlock()
        completionHandler(nil)
    }
}
