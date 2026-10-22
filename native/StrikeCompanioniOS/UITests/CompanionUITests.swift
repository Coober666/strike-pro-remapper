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

    func testTerminationAcknowledgementMatcherRejectsUnrelatedFailures() {
        let expected = "Failed to terminate net.cooberlab.strike-companion.ios:10129: Failed to terminate net.cooberlab.strike-companion.ios:0"
        XCTAssertTrue(SimulatorTerminationAcknowledgement.matches(expected))
        for other in ["App must be stopped before relaunch", "Failed to terminate net.cooberlab.strike-companion.ios:10129",
                      expected + " (still running)", expected.replacingOccurrences(of: ":10129:", with: ":0:"),
                      expected.replacingOccurrences(of: "strike-companion.ios", with: "another-app"),
                      "Cold-launch song restoration failed", "Prefix " + expected] {
            XCTAssertFalse(SimulatorTerminationAcknowledgement.matches(other), other)
        }
    }

    func testRenamedWelcomeOffersKitEditorAndSetlistPerformance() {
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.launchEnvironment["STRIKE_UI_TEST_SESSION"] = UUID().uuidString
        app.stopForUITestRelaunch()
        app.launch()
        XCTAssertTrue(app.navigationBars["Strike Remapper"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["import"].exists)
        app.buttons["welcome-kit"].tap()
        XCTAssertTrue(app.buttons["kit-demo"].waitForExistence(timeout: 5))
        app.buttons["close-inspector"].tap()
        app.buttons["demo"].tap()
        XCTAssertEqual(app.staticTexts["song-title"].label, "Soundcheck")
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
        // Three cold launches, including two document handoffs. Hosted launch
        // setup alone can exceed 100 seconds; retain the builder's 300s ceiling.
        executionTimeAllowance = 300
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
        XCTAssertTrue(imported.waitForExistence(timeout: 10), "Invalid Open In must retain the imported song")
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
        let snare = app.kitZone("S1H")
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
        let snare = app.kitZone("S1H")
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
    func kitZone(_ zone: String) -> XCUIElement {
        // matching(identifier:) also searches label/value via XCElementSnapshot.identifiers.
        // Hosted Xcode 27 can stall fetching those values from the complete SwiftUI tree.
        // Match only the explicit accessibilityIdentifier; retain Any for legacy/wide layouts.
        descendants(matching: .any).matching(NSPredicate(format: "identifier == %@", "kit-zone-" + zone)).firstMatch
    }

    func stopForUITestRelaunch() {
        guard state != .notRunning else { return }
        // Hosted XCTest has failed foreground termination with stale PID errors.
        // Complete backgrounding and explicit termination before a new launch.
        if state == .runningForeground { XCUIDevice.shared.press(.home) }
        // The previous test's process may already be exiting while XCTest still
        // reports its old PID. Let the stopped state arrive before requesting
        // termination; never retry a failed terminate or launch over a live app.
        let alreadyStopped = wait(for: .notRunning, timeout: 5)
        // Files can report stale foreground state even after Home is visible.
        // Require the final stopped state, not an intermediate background flag.
        if !alreadyStopped && state != .notRunning {
            #if compiler(>=6.3)
            let options = XCTExpectedFailure.Options()
            options.isStrict = false
            options.issueMatcher = { SimulatorTerminationAcknowledgement.matches($0.compactDescription) }
            // Match only the SDK's exact old-PID -> PID-zero acknowledgement error.
            // The actual stopped-state assertion below is OUTSIDE this scope.
            XCTExpectFailure("Xcode stale-PID termination acknowledgement; process exit is verified separately", options: options) {
                terminate()
            }
            #else
            terminate()
            #endif
        }
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
        enum Kind: String { case cancel = "Cancel", recents = "Recents" }
        struct Candidate {
            let kind: Kind
            let identifier: String
            let parentType: XCUIElement.ElementType?
            let parentIdentifier: String
            let parentLabel: String
        }
        struct Selection {
            let kind: Kind
            let control: XCUIElement
            let hostFrame: CGRect
        }
        let files = XCUIApplication(bundleIdentifier: "com.apple.DocumentManagerUICore.Service")
        var poll = 0
        var diagnostics: [String] = []
        func record(_ message: String) {
            let line = "Files cancellation poll=\(poll) \(message)"
            print(line)
            diagnostics.append(line)
            if diagnostics.count > 12 { diagnostics.removeFirst() }
        }
        func validFrame(_ frame: CGRect, inside bounds: CGRect) -> Bool {
            !frame.isEmpty && !frame.isNull && !frame.isInfinite &&
                frame.minX.isFinite && frame.minY.isFinite &&
                frame.maxX.isFinite && frame.maxY.isFinite && bounds.contains(frame)
        }
        func candidates(in snapshot: any XCUIElementSnapshot, service: Bool,
                        hostFrame: CGRect, allowRecents: Bool) -> [Candidate] {
            var matches: [Candidate] = []
            func visit(_ node: any XCUIElementSnapshot, navigation: (any XCUIElementSnapshot)?,
                       tabBar: (any XCUIElementSnapshot)?) {
                let navigation = node.elementType == .navigationBar ? node : navigation
                let tabBar = node.elementType == .tabBar ? node : tabBar
                if node.elementType == .button && node.isEnabled && validFrame(node.frame, inside: hostFrame) {
                    let kind: Kind? = node.label == "Cancel" && (navigation != nil || service) ? .cancel :
                        (allowRecents && node.label == "Recents" && tabBar != nil ? .recents : nil)
                    if let kind {
                        let parent = kind == .cancel ? navigation : tabBar
                        matches.append(Candidate(kind: kind, identifier: node.identifier,
                                                 parentType: parent?.elementType,
                                                 parentIdentifier: parent?.identifier ?? "",
                                                 parentLabel: parent?.label ?? ""))
                    }
                }
                for child in node.children { visit(child, navigation: navigation, tabBar: tabBar) }
            }
            visit(snapshot, navigation: nil, tabBar: nil)
            return matches.filter { $0.kind == .cancel } + matches.filter { $0.kind == .recents }
        }
        func resolve(_ candidate: Candidate, in root: XCUIApplication, hostFrame: CGRect) -> XCUIElement? {
            var buttons = root.buttons
            if let parentType = candidate.parentType {
                var parents = root.descendants(matching: parentType)
                if !candidate.parentIdentifier.isEmpty {
                    parents = parents.matching(NSPredicate(format: "identifier == %@", candidate.parentIdentifier))
                } else if !candidate.parentLabel.isEmpty {
                    parents = parents.matching(NSPredicate(format: "label == %@", candidate.parentLabel))
                }
                buttons = parents.buttons
            }
            var predicate = NSPredicate(format: "label == %@", candidate.kind.rawValue)
            if !candidate.identifier.isEmpty {
                predicate = NSCompoundPredicate(andPredicateWithSubpredicates: [predicate,
                    NSPredicate(format: "identifier == %@", candidate.identifier)])
            }
            let control = buttons.matching(predicate).firstMatch
            // No exists preflight: it can block/retry against an incomplete remote
            // tree. Resolve only a real button already found in the root snapshot.
            guard let fresh = try? control.snapshot(), fresh.elementType == .button,
                  fresh.label == candidate.kind.rawValue, fresh.isEnabled,
                  validFrame(fresh.frame, inside: hostFrame), control.isHittable else { return nil }
            return control
        }
        func inspect(_ snapshot: any XCUIElementSnapshot, root: XCUIApplication,
                     name: String, state: XCUIApplication.State, hostFrame: CGRect,
                     allowRecents: Bool) -> Selection? {
            let matches = candidates(in: snapshot, service: name == "service", hostFrame: hostFrame,
                                     allowRecents: allowRecents)
            for candidate in matches {
                if let control = resolve(candidate, in: root, hostFrame: hostFrame) {
                    record("root=\(name) state=\(state.rawValue) candidates=\(matches.count) choice=\(candidate.kind.rawValue)")
                    return Selection(kind: candidate.kind, control: control, hostFrame: hostFrame)
                }
            }
            record("root=\(name) state=\(state.rawValue) candidates=\(matches.count) choice=none")
            return nil
        }
        func available(allowRecents: Bool) -> Selection? {
            poll += 1
            let hostState = self.state
            // One throwing snapshot per queried root, then walk children locally.
            // Host-first preserves the real NavigationBar Cancel seen in run39702644297.
            guard let host = try? snapshot() else {
                record("root=host state=\(hostState.rawValue) snapshot=unavailable; service=not-queried-without-host-bounds")
                return nil
            }
            guard validFrame(host.frame, inside: host.frame) else {
                record("root=host state=\(hostState.rawValue) bounds=invalid; service=not-queried-without-host-bounds")
                return nil
            }
            if let selection = inspect(host, root: self, name: "host", state: hostState,
                                       hostFrame: host.frame, allowRecents: allowRecents) { return selection }
            let serviceState = files.state
            guard serviceState != .notRunning else {
                record("root=service state=\(serviceState.rawValue) snapshot=not-queried")
                return nil
            }
            guard let service = try? files.snapshot() else {
                record("root=service state=\(serviceState.rawValue) snapshot=unavailable")
                return nil
            }
            return inspect(service, root: files, name: "service", state: serviceState,
                           hostFrame: host.frame, allowRecents: allowRecents)
        }
        func waitForControl(allowRecents: Bool) -> Selection? {
            var selection: Selection?
            let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                selection = available(allowRecents: allowRecents)
                return selection != nil
            }, object: nil)
            let result = XCTWaiter.wait(for: [ready], timeout: 90)
            if result != .completed {
                let screen = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
                screen.name = "Files cancellation readiness failure"; screen.lifetime = .keepAlways
                XCTContext.runActivity(named: "Files cancellation readiness diagnostics") { $0.add(screen) }
            }
            XCTAssertEqual(result, .completed, diagnostics.joined(separator: "\n"))
            return result == .completed ? selection : nil
        }
        func tapControl(_ selection: Selection) {
            // Revalidate the actual button immediately before its one host tap.
            // The Files extension itself cannot reliably be activated by XCTest.
            guard let fresh = try? selection.control.snapshot(), fresh.elementType == .button,
                  fresh.label == selection.kind.rawValue, fresh.isEnabled,
                  validFrame(fresh.frame, inside: selection.hostFrame), selection.control.isHittable else {
                XCTFail("Files control stopped being actionable before its single tap. " + diagnostics.joined(separator: "\n"))
                return
            }
            coordinate(withNormalizedOffset: .zero)
                .withOffset(CGVector(dx: fresh.frame.midX - selection.hostFrame.minX,
                                     dy: fresh.frame.midY - selection.hostFrame.minY)).tap()
        }
        guard let selection = waitForControl(allowRecents: true) else { return }
        tapControl(selection)
        if selection.kind == .recents {
            // Only an actual TabBar button may reveal Cancel. A Recents sidebar
            // cell, generic Other, or More control is never an acceptable proxy.
            guard let cancel = waitForControl(allowRecents: false) else { return }
            tapControl(cancel)
        }
    }
}


/// Scope only the observed XCTest acknowledgement diagnostic, never an app assertion.
enum SimulatorTerminationAcknowledgement {
    static func matches(_ description: String) -> Bool {
        let pattern = #"^Failed to terminate net\.cooberlab\.strike-companion\.ios:[1-9][0-9]*: Failed to terminate net\.cooberlab\.strike-companion\.ios:0$"#
        return description.range(of: pattern, options: .regularExpression) == description.startIndex..<description.endIndex
    }
}
