import XCTest
import UIKit

@MainActor
final class KitEditingUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    private func launchKit() -> XCUIApplication {
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.launchEnvironment["STRIKE_UI_TEST_SESSION"] = UUID().uuidString
        app.launch()
        app.buttons["demo"].tap()
        app.buttons["kit-inspector"].tap()
        app.buttons["kit-demo"].tap()
        let snare = app.descendants(matching: .any).matching(identifier: "kit-zone-S1H").firstMatch
        XCTAssertTrue(snare.waitForExistence(timeout: 10))
        snare.tap()
        XCTAssertTrue(app.buttons["kit-edit-aLevel"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["kit-edit-status"].firstMatch.exists)
        return app
    }
    private func replace(_ field: XCUIElement, with text: String) {
        // Use the visible replacement action instead of assuming a caret position in a right-aligned field.
        let clear = XCUIApplication().buttons["kit-edit-clear"]
        XCTAssertTrue(clear.waitForExistence(timeout: 5))
        clear.tap()
        field.typeText(text)
        XCTAssertEqual(field.value as? String, text)
        // The iPad keyboard moves this sheet before the remote AX frame catches up.
        // Done ends text entry without applying; then the explicit toolbar action is stable.
        field.typeText("\n")
        XCTAssertTrue(XCUIApplication().buttons["kit-edit-apply"].exists)
    }
    private func reveal(_ element: XCUIElement, app: XCUIApplication) {
        let scroll = app.scrollViews["kit-detail"]
        let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            !app.buttons["kit-edit-apply"].exists
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [dismissed], timeout: 5), .completed)
        func visible() -> Bool {
            guard element.exists else { return false }
            let frame = element.frame
            let viewport = scroll.frame.intersection(app.frame).insetBy(dx: 1, dy: 64)
            // Hosted AX can throw instead of returning false for an offscreen activation point.
            // Scroll its frame into the unobscured viewport before querying hittability.
            guard !frame.isEmpty, !frame.isInfinite,
                  viewport.contains(CGPoint(x: frame.midX, y: frame.midY)) else { return false }
            return element.isHittable
        }
        for _ in 0..<9 {
            if visible() { return }
            if element.exists && element.frame.midY < scroll.frame.minY + 64 { scroll.swipeDown() }
            else { scroll.swipeUp() }
        }
        XCTAssertTrue(visible(), "Could not reveal the requested kit control")
    }
    private func menu(_ action: String, app: XCUIApplication) {
        let menu = app.buttons["kit-actions"]
        let item = app.buttons[action]
        menu.tap()
        // A first post-sheet tap can finish keyboard dismissal on iPad. Retry presentation only.
        if !item.waitForExistence(timeout: 3) { menu.tap() }
        XCTAssertTrue(item.waitForExistence(timeout: 5), app.debugDescription)
        item.tap()
    }
    private func screenshot(_ name: String) {
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.name = name; shot.lifetime = .keepAlways; add(shot)
    }
    func testExplicitApplyCancelBoundsUndoRedoAndRetainedEditsAfterDone() {
        let app = launchKit()
        app.buttons["kit-edit-aLevel"].tap()
        let field = app.textFields["kit-edit-value"]
        XCTAssertEqual(field.value as? String, "100")
        let slider = app.sliders["kit-edit-slider"]
        XCTAssertTrue(slider.isHittable)
        slider.adjust(toNormalizedSliderPosition: 0.25)
        let quickValue = Int(field.value as? String ?? "")
        XCTAssertNotNil(quickValue)
        XCTAssertTrue((1...59).contains(quickValue ?? -1))
        screenshot("Quick numeric adjustment")
        field.tap() // First focus selects the whole number, including when the tap is left of its digits.
        field.typeText("128")
        XCTAssertFalse(app.buttons["kit-edit-apply"].isEnabled)
        XCTAssertEqual(field.value as? String, "128") // Moving the thumb's display must not clamp typed input.
        app.buttons["kit-edit-clear"].tap()
        field.typeText("73")
        screenshot("Layer A value editor")
        app.buttons["kit-edit-cancel"].tap()
        XCTAssertTrue(app.buttons["kit-edit-aLevel"].label.contains("100"))
        app.buttons["kit-edit-aLevel"].tap()
        replace(field, with: "73")
        app.buttons["kit-edit-apply"].tap()
        XCTAssertTrue(app.buttons["kit-edit-aLevel"].label.contains("73"))
        menu("kit-undo", app: app)
        XCTAssertTrue(app.buttons["kit-edit-aLevel"].label.contains("100"))
        menu("kit-redo", app: app)
        XCTAssertTrue(app.buttons["kit-edit-aLevel"].label.contains("73"))
        app.buttons["close-inspector"].tap()
        XCTAssertTrue(app.staticTexts["song-title"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["song-title"].label, "Soundcheck")
        app.buttons["kit-inspector"].tap()
        app.descendants(matching: .any).matching(identifier: "kit-zone-S1H").firstMatch.tap()
        XCTAssertTrue(app.buttons["kit-edit-aLevel"].label.contains("73"))
        screenshot("Edited kit portrait")
        XCUIDevice.shared.orientation = .landscapeLeft
        let rotated = NSPredicate { _, _ in app.frame.width > app.frame.height }
        expectation(for: rotated, evaluatedWith: nil); waitForExpectations(timeout: 10)
        XCTAssertTrue(app.buttons["kit-actions"].isHittable)
        XCTAssertTrue(app.buttons["close-inspector"].isHittable)
        screenshot("Edited kit landscape")
    }
    func testAssignmentsBothLayersAndSignedValue() {
        let app = launchKit()
        app.buttons["kit-assign-0"].tap()
        app.buttons["kit-reference-0"].tap()
        app.buttons["kit-edit-apply"].tap()
        XCTAssertEqual(app.staticTexts["kit-layer-a"].label, "Synthetic/Kick.sin")
        let pan = app.buttons["kit-edit-aPan"]
        reveal(pan, app: app)
        pan.tap()
        replace(app.textFields["kit-edit-value"], with: "-17")
        app.buttons["kit-edit-apply"].tap()
        XCTAssertTrue(pan.label.contains("-17"))
        let assignB = app.buttons["kit-assign-1"]
        reveal(assignB, app: app)
        assignB.tap()
        app.buttons["kit-reference-65535"].tap()
        screenshot("Layer B assignment")
        app.buttons["kit-edit-apply"].tap()
        XCTAssertEqual(app.staticTexts["kit-layer-b"].label, "Unassigned")
        let levelB = app.buttons["kit-edit-bLevel"]
        reveal(levelB, app: app)
        levelB.tap()
        replace(app.textFields["kit-edit-value"], with: "65")
        app.buttons["kit-edit-apply"].tap()
        XCTAssertTrue(levelB.label.contains("65"))
        menu("kit-undo", app: app)
        XCTAssertTrue(levelB.label.contains("80"))
        menu("kit-undo", app: app)
        XCTAssertEqual(app.staticTexts["kit-layer-b"].label, "Synthetic/Brush Snare.sin")
    }
    func testReplacementRequiresDiscardAndExportFolderCancellationKeepsEdits() {
        executionTimeAllowance = 300
        let app = launchKit()
        app.buttons["kit-edit-aLevel"].tap()
        replace(app.textFields["kit-edit-value"], with: "71")
        app.buttons["kit-edit-apply"].tap()
        menu("kit-reload-demo", app: app)
        XCTAssertTrue(app.alerts["Replace the edited kit?"].waitForExistence(timeout: 5))
        app.alerts.buttons["Keep editing"].tap()
        XCTAssertTrue(app.buttons["kit-edit-aLevel"].label.contains("71"))
        menu("kit-export", app: app)
        screenshot("Choose export folder")
        app.cancelFilesPicker()
        let dismissed = NSPredicate { _, _ in app.buttons["kit-actions"].isHittable && app.buttons["kit-actions"].isEnabled }
        let resumed = XCTNSPredicateExpectation(predicate: dismissed, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [resumed], timeout: 15), .completed, app.debugDescription)
        XCTAssertTrue(app.buttons["kit-edit-aLevel"].label.contains("71"))
        XCTAssertFalse(app.alerts.firstMatch.exists)
        menu("kit-reload-demo", app: app)
        app.alerts.buttons["Discard edits and open kit"].tap()
        let snare = app.descendants(matching: .any).matching(identifier: "kit-zone-S1H").firstMatch
        XCTAssertTrue(snare.waitForExistence(timeout: 5))
        snare.tap()
        XCTAssertTrue(app.buttons["kit-edit-aLevel"].label.contains("100"))
    }
    func testEditExportThroughFilesAndReopenCopy() {
        // Cold hosted Files providers can take over three minutes; all assertions remain required.
        executionTimeAllowance = 300
        let app = launchKit()
        app.buttons["kit-edit-aLevel"].tap()
        replace(app.textFields["kit-edit-value"], with: "72")
        app.buttons["kit-edit-apply"].tap()
        menu("kit-export", app: app)
        let local = app.staticTexts[UIDevice.current.userInterfaceIdiom == .pad ? "On My iPad" : "On My iPhone"]
        // Files may restore our app folder directly or retain it behind the Browse tab.
        let atDestination = {
            app.buttons["Strike Companion, Actions Menu"].exists ||
                app.navigationBars.staticTexts["Strike Companion"].exists
        }
        let pickerReady = NSPredicate { _, _ in atDestination() || local.exists || app.buttons["Browse"].exists }
        expectation(for: pickerReady, evaluatedWith: nil); waitForExpectations(timeout: 30)
        if !atDestination() && !local.exists { app.buttons["Browse"].tap() }
        if !atDestination() {
            XCTAssertTrue(local.waitForExistence(timeout: 10), app.debugDescription)
            local.tap()
            let companion = app.staticTexts["Strike Companion"].firstMatch
            XCTAssertTrue(companion.waitForExistence(timeout: 10), app.debugDescription)
            companion.tap()
        }
        screenshot("Export destination")
        app.buttons["Open"].tap()
        XCTAssertTrue(app.staticTexts["kit-export-status"].waitForExistence(timeout: 10), app.debugDescription)
        let message = app.staticTexts["kit-export-status"].label
        XCTAssertTrue(message.contains("Created Kit-edit-"))
        let name = message.components(separatedBy: " ")[1]
        screenshot("Exported copy verified")
        app.buttons["import-kit"].tap()
        let file = app.cells.containing(.staticText, identifier: name).firstMatch
        XCTAssertTrue(file.waitForExistence(timeout: 10), app.debugDescription)
        screenshot("Select exported copy")
        // Let XCTest reveal/activate the actual image in icon view; coordinate taps can miss
        // hosted Files items after it scrolls or relays accessibility through another process.
        let icon = file.images.firstMatch
        if icon.exists { icon.tap() }
        else { file.tap() } // List view has one directly activatable row.
        XCTAssertTrue(app.alerts["Replace the edited kit?"].waitForExistence(timeout: 10))
        app.alerts.buttons["Discard edits and open kit"].tap()
        let snare = app.descendants(matching: .any).matching(identifier: "kit-zone-S1H").firstMatch
        XCTAssertTrue(snare.waitForExistence(timeout: 5))
        snare.tap()
        XCTAssertTrue(app.buttons["kit-edit-aLevel"].label.contains("72"))
        XCTAssertEqual(app.staticTexts["kit-layer-a"].label, "Synthetic/Snare.sin")
        screenshot("Reopened exported copy")
    }

}
