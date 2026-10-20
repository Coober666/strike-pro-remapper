import XCTest
import UIKit

@MainActor
final class CompanionUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    private func launchDemo() -> XCUIApplication {
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.launchEnvironment["STRIKE_UI_TEST_SESSION"] = UUID().uuidString
        app.stopForUITestRelaunch()
        app.launch()
        app.buttons["demo"].tap()
        XCTAssertTrue(app.staticTexts["song-title"].waitForExistence(timeout: 5))
        return app
    }

    func testRunningOrderSearchNavigationAndPerformanceView() {
        let app = launchDemo()
        XCTAssertEqual(app.staticTexts["song-title"].label, "Soundcheck")
        XCTAssertFalse(app.buttons["previous"].isEnabled)
        app.buttons["next"].tap()
        XCTAssertEqual(app.staticTexts["song-title"].label, "Paper Satellites")
        if app.buttons["songs"].exists { app.buttons["songs"].tap() }
        let search = app.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        search.tap()
        search.typeText("guitar")
        // Keep text entry and explicit keyboard submission independently observable.
        search.typeText("\n")
        XCTAssertTrue(app.buttons["song-2"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["song-0"].exists)
        app.buttons["song-2"].tap()
        app.buttons["next"].tap()
        XCTAssertEqual(app.staticTexts["song-title"].label, "Lights on the Water")
        XCTAssertFalse(app.buttons["next"].isEnabled)
        app.buttons["reading-options"].tap()
        app.buttons["performance"].tap()
        XCTAssertTrue(app.buttons["songs"].exists)
        app.buttons["reading-options"].tap()
        app.buttons["Extra large"].tap()
        app.buttons["previous"].tap()
        XCTAssertEqual(app.staticTexts["song-title"].label, "After the Last Train")
        XCTAssertTrue(app.buttons["next"].isHittable)
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.name = "Performance portrait"
        shot.lifetime = .keepAlways
        add(shot)
        XCUIDevice.shared.orientation = .landscapeLeft
        XCTAssertTrue(app.buttons["next"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["next"].isHittable)
        let rotated = NSPredicate { _, _ in app.frame.width > app.frame.height }
        expectation(for: rotated, evaluatedWith: nil)
        waitForExpectations(timeout: 10)
        app.buttons["next"].tap()
        XCTAssertEqual(app.staticTexts["song-title"].label, "Lights on the Water")
        let landscape = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        landscape.name = "Performance landscape"
        landscape.lifetime = .keepAlways
        add(landscape)
    }

    func testOpenInImportAndInvalidFileRejection() throws {
        #if compiler(<6.3)
        throw XCTSkip("Xcode 16/26 file-URL automation does not deliver documents. The Xcode 27 CI job runs this test; model import contracts run on both.")
        #else
        let app = launchDemo()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let valid = Data(#"{"format":"strike-setlist","version":1,"name":"UI imported show","numbered":false,"entries":[{"kit":"UI.skt","song":"Imported opener","notes":"Four count"}]}"#.utf8)
        try valid.write(to: file)
        // Target this viewer explicitly; default-app file dispatch can time out
        // in hosted simulators. open() is a launch operation, so active-session
        // retention is covered by the model tests and attended device checks.
        app.stopForUITestRelaunch()
        app.open(file)
        let imported = app.staticTexts["Imported opener"]
        XCTAssertTrue(imported.waitForExistence(timeout: 10))
        let invalid = Data("not JSON".utf8)
        try invalid.write(to: file)
        app.stopForUITestRelaunch()
        app.open(file)
        XCTAssertTrue(app.alerts.firstMatch.waitForExistence(timeout: 10))
        app.alerts.buttons["OK"].tap()
        XCTAssertFalse(app.alerts.firstMatch.exists)
        XCTAssertEqual(try Data(contentsOf: file), invalid)
        #endif
    }

    func testAdaptiveLayoutAndScrollReset() {
        let app = launchDemo()
        XCUIDevice.shared.orientation = .landscapeLeft
        let rotated = NSPredicate { _, _ in app.frame.width > app.frame.height }
        expectation(for: rotated, evaluatedWith: nil)
        waitForExpectations(timeout: 10)
        if UIDevice.current.userInterfaceIdiom == .pad {
            XCTAssertTrue(app.buttons["song-0"].waitForExistence(timeout: 5))
            XCTAssertFalse(app.buttons["songs"].exists)
        } else {
            XCTAssertTrue(app.buttons["songs"].exists)
        }
        app.buttons["next"].tap()
        XCTAssertEqual(app.staticTexts["song-title"].label, "Paper Satellites")
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.name = "Adaptive landscape"
        shot.lifetime = .keepAlways
        add(shot)
        app.scrollViews["song-sheet"].swipeUp()
        app.buttons["next"].tap()
        XCTAssertTrue(app.staticTexts["song-title"].isHittable)
        XCTAssertEqual(app.staticTexts["song-title"].label, "After the Last Train")
    }

    func testColdLaunchRestoresSongAndReadingPreferences() {
        let app = launchDemo()
        app.buttons["next"].tap()
        app.buttons["reading-options"].tap()
        app.buttons["performance"].tap()
        app.buttons["reading-options"].tap()
        app.buttons["Extra large"].tap()
        app.stopForUITestRelaunch()
        app.launch()
        XCTAssertTrue(app.staticTexts["song-title"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["song-title"].label, "Paper Satellites")
        app.buttons["reading-options"].tap()
        XCTAssertTrue(app.buttons["Leave performance view"].exists)
    }

    func testFilePickerCancellationPreservesSong() {
        executionTimeAllowance = 300 // Cold hosted Files accessibility can arrive after its window renders.
        let app = launchDemo()
        app.buttons["next"].tap()
        app.buttons["import"].tap()
        app.cancelFilesPicker()
        let dismissed = NSPredicate { _, _ in
            app.buttons["import"].isHittable && app.buttons["import"].isEnabled
        }
        let resumed = XCTNSPredicateExpectation(predicate: dismissed, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [resumed], timeout: 15), .completed, app.debugDescription)
        XCTAssertEqual(app.staticTexts["song-title"].label, "Paper Satellites")
        XCTAssertFalse(app.alerts.firstMatch.exists)
    }
    func testKitInspectorLayersAndReturnToSetlist() {
        let app = launchDemo()
        app.buttons["next"].tap()
        app.buttons["kit-inspector"].tap()
        app.buttons["kit-demo"].tap()
        let snare = app.descendants(matching: .any).matching(identifier: "kit-zone-S1H").firstMatch
        XCTAssertTrue(snare.waitForExistence(timeout: 10))
        snare.tap()
        XCTAssertTrue(app.staticTexts["kit-layer-a"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["kit-layer-a"].label, "Synthetic/Snare.sin")
        let layerB = app.staticTexts["kit-layer-b"]
        for _ in 0..<6 {
            if layerB.isHittable { break }
            app.scrollViews["kit-detail"].swipeUp()
        }
        XCTAssertEqual(layerB.label, "Synthetic/Brush Snare.sin")
        XCTAssertEqual(app.staticTexts["kit-pad-title"].label, "Snare Head")
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.name = "Kit inspector layers"
        shot.lifetime = .keepAlways
        add(shot)
        app.buttons["close-inspector"].tap()
        XCTAssertTrue(app.staticTexts["song-title"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["song-title"].label, "Paper Satellites")
    }

    func testKitOpenInRoutesToInspector() throws {
        #if compiler(<6.3)
        throw XCTSkip("Explicit document launch requires Xcode 27; model import tests run on both.")
        #else
        let app = launchDemo()
        let source = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".skt")
        defer { try? FileManager.default.removeItem(at: source) }
        var bytes = Data("KIT ".utf8) + Data([44, 0, 0, 0]) + Data(repeating: 0, count: 44)
        bytes += Data("inst".utf8) + Data([64, 0, 0, 0])
        var pad = Data(repeating: 0, count: 64)
        pad.replaceSubrange(0..<4, with: Data("S1H ".utf8))
        pad[24] = 255; pad[25] = 255
        bytes += pad + Data("str ".utf8) + Data([9, 0, 0, 0]) + Data("Demo.sin\0".utf8)
        try bytes.write(to: source)
        app.stopForUITestRelaunch()
        app.open(source)
        let snare = app.descendants(matching: .any).matching(identifier: "kit-zone-S1H").firstMatch
        XCTAssertTrue(snare.waitForExistence(timeout: 10))
        snare.tap()
        XCTAssertTrue(app.staticTexts["kit-layer-a"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["kit-layer-a"].label, "Demo.sin")
        XCTAssertEqual(app.staticTexts["kit-layer-b"].label, "Unassigned")
        XCTAssertEqual(try Data(contentsOf: source), bytes)
        app.buttons["close-inspector"].tap()
        XCTAssertTrue(app.staticTexts["song-title"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["song-title"].label, "Soundcheck")
        #endif
    }

}

@MainActor
extension XCUIApplication {
    func stopForUITestRelaunch() {
        guard state != .notRunning else { return }
        // Hosted XCTest has failed foreground termination with stale PID errors.
        // Complete backgrounding and explicit termination before a new launch.
        if state == .runningForeground { XCUIDevice.shared.press(.home) }
        // A hosted Files session can report a stale foreground state even after
        // Home is visible. Require the final stopped state, not a transient one.
        if state != .notRunning { terminate() }
        let stopped = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            self.state == .notRunning
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [stopped], timeout: 10), .completed,
                       "App must be stopped before relaunch; state=\(state.rawValue)")
    }

    func actionableFilesControl(_ query: (XCUIApplication) -> XCUIElement) -> XCUIElement? {
        let files = XCUIApplication(bundleIdentifier: "com.apple.DocumentManagerUICore.Service")
        // The host may expose misleading generic proxies for hosted Files controls.
        // Query real buttons and reject stale/offscreen/covered activation points.
        func actionable(_ control: XCUIElement) -> Bool {
            // Files can replace its tab bar between AX queries while restoring a folder.
            // Read frame/enabled together; a disappearing match throws from snapshot()
            // and is retried by the bounded predicate instead of failing a frame getter.
            guard control.exists, let snapshot = try? control.snapshot(), snapshot.isEnabled else { return false }
            let frame = snapshot.frame
            guard !frame.isEmpty, !frame.isInfinite,
                  self.frame.contains(CGPoint(x: frame.midX, y: frame.midY)) else { return false }
            return control.isHittable
        }
        if files.state != .notRunning {
            let control = query(files)
            if actionable(control) { return control }
        }
        let control = query(self)
        return actionable(control) ? control : nil
    }

    func cancelFilesPicker() {
        func cancelControl() -> XCUIElement? {
            actionableFilesControl { $0.buttons["Cancel"].firstMatch }
        }
        func recentsTab() -> XCUIElement? {
            actionableFilesControl { $0.tabBars.buttons["Recents"].firstMatch }
        }
        let ready = NSPredicate { _, _ in cancelControl() != nil || recentsTab() != nil }
        let picker = XCTNSPredicateExpectation(predicate: ready, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [picker], timeout: 90), .completed, debugDescription)
        if let control = cancelControl() {
            control.tap()
            return
        }
        // A restored folder can hide Cancel. Use the actual bottom tab, not a
        // generic Recents proxy or More, which opens sorting options on modern Files.
        guard let recents = recentsTab() else {
            XCTFail("No actionable Files Cancel button or Recents tab. \(debugDescription)")
            return
        }
        recents.tap()
        let command = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            cancelControl() != nil
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [command], timeout: 90), .completed, debugDescription)
        guard let control = cancelControl() else {
            XCTFail("Files did not expose an actionable Cancel button. \(debugDescription)")
            return
        }
        control.tap()
    }
}
