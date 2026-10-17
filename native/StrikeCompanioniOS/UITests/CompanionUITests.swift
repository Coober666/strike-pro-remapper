import XCTest
import UIKit

@MainActor
final class CompanionUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    private func launchDemo() -> XCUIApplication {
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
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
        let app = launchDemo()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let valid = Data(#"{"format":"strike-setlist","version":1,"name":"UI imported show","numbered":false,"entries":[{"kit":"UI.skt","song":"Imported opener","notes":"Four count"}]}"#.utf8)
        try valid.write(to: file)
        // Route the document through the OS. Xcode 16's app.open(file) relaunches
        // the app without delivering the file URL to its scene.
        XCUIDevice.shared.system.open(file)
        app.activate()
        let imported = app.staticTexts["Imported opener"]
        XCTAssertTrue(imported.waitForExistence(timeout: 10))
        let invalid = Data("not JSON".utf8)
        try invalid.write(to: file)
        XCUIDevice.shared.system.open(file)
        app.activate()
        XCTAssertTrue(app.alerts.firstMatch.waitForExistence(timeout: 10))
        app.alerts.buttons["OK"].tap()
        XCTAssertFalse(app.alerts.firstMatch.exists)
        XCTAssertEqual(app.staticTexts["song-title"].label, "Imported opener")
        XCTAssertEqual(try Data(contentsOf: file), invalid)
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

    func testFilePickerCancellationPreservesSong() {
        let app = launchDemo()
        app.buttons["next"].tap()
        app.buttons["import"].tap()
        let cancel = app.buttons["Cancel"]
        XCTAssertTrue(cancel.waitForExistence(timeout: 10))
        cancel.tap()
        XCTAssertEqual(app.staticTexts["song-title"].label, "Paper Satellites")
        XCTAssertFalse(app.alerts.firstMatch.exists)
    }
}
