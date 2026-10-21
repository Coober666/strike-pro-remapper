import XCTest
import UIKit

@MainActor
final class NativeMIDIUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    private func launch() -> XCUIApplication {
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.launchEnvironment["STRIKE_UI_TEST_SESSION"] = UUID().uuidString
        app.launchEnvironment["STRIKE_UI_TEST_MIDI"] = "1"
        app.stopForUITestRelaunch(); app.launch()
        app.buttons["midi-tools"].tap()
        return app
    }
    func testExplicitInputCaptureLearnStopAndRetainedTake() {
        let app = launch()
        XCTAssertFalse(app.buttons["midi-record"].isEnabled)
        app.buttons["midi-refresh"].tap()
        XCTAssertFalse(app.buttons["midi-record"].isEnabled)
        app.buttons["midi-input"].tap()
        app.buttons["Synthetic drum input"].tap()
        XCTAssertGreaterThanOrEqual(app.buttons["midi-record"].frame.height, 44)
        app.buttons["midi-record"].tap()
        XCTAssertTrue(app.buttons["midi-stop"].isEnabled)
        XCTAssertGreaterThanOrEqual(app.buttons["midi-stop"].frame.height, 44)
        XCTAssertTrue(app.staticTexts["midi-count"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["midi-count"].label.contains("recording"))
        XCTAssertFalse(app.staticTexts["midi-count"].label.contains("complete"))
        app.buttons["midi-learn"].tap()
        let candidate = app.staticTexts["midi-candidate"]
        XCTAssertTrue(candidate.waitForExistence(timeout: 5))
        XCTAssertTrue(candidate.label.contains("Channel 10, note 38, velocity 96"))
        let field = app.textFields["midi-pad-name"]
        XCTAssertGreaterThanOrEqual(field.frame.height, 44)
        field.tap(); field.typeText("Snare")
        XCTAssertEqual(field.value as? String, "Snare")
        field.typeText("\n")
        app.buttons["midi-apply-name"].tap()
        XCTAssertTrue(app.staticTexts["Ch 10 / 38: Snare"].waitForExistence(timeout: 5))
        app.buttons["midi-stop"].tap()
        XCTAssertTrue(app.staticTexts["midi-count"].label.contains("complete"))
        XCTAssertTrue(app.buttons["midi-export"].isEnabled)
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.name = "Native MIDI input and confirmed Learn"; shot.lifetime = .keepAlways; add(shot)
        app.buttons["midi-record"].tap()
        app.buttons["Keep take"].tap()
        XCTAssertTrue(app.staticTexts["midi-count"].label.contains("complete"))
        app.buttons["midi-done"].tap()
        app.buttons["midi-tools"].tap()
        XCTAssertTrue(app.staticTexts["midi-count"].label.contains("complete"))
        XCTAssertFalse(app.buttons["midi-stop"].isEnabled)
    }
    func testBackgroundStopsPartialAndDoesNotRestartOnReturn() {
        let app = launch()
        app.buttons["midi-refresh"].tap()
        app.buttons["midi-input"].tap(); app.buttons["Synthetic drum input"].tap()
        app.buttons["midi-record"].tap()
        XCTAssertTrue(app.buttons["midi-stop"].isEnabled)
        XCUIDevice.shared.press(.home)
        app.activate()
        XCTAssertTrue(app.staticTexts["midi-count"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["midi-count"].label.contains("partial"))
        XCTAssertFalse(app.buttons["midi-stop"].isEnabled)
        XCTAssertTrue(app.buttons["midi-export"].isEnabled)
    }
}
