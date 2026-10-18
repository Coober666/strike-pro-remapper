import SwiftUI

@main
struct StrikeCompanionMobileApp: App {
    @StateObject private var model: MobileCompanionModel

    init() {
        var store = CompanionSessionStore.live
        #if DEBUG
        // UI tests use a private app-container slot, never the owner’s saved session.
        if let slot = ProcessInfo.processInfo.environment["STRIKE_UI_TEST_SESSION"], UUID(uuidString: slot) != nil {
            store = CompanionSessionStore(url: FileManager.default.temporaryDirectory
                .appendingPathComponent("UITests/\(slot)/session.json"))
        }
        #endif
        _model = StateObject(wrappedValue: MobileCompanionModel(store: store))
    }
    var body: some Scene {
        WindowGroup { MobileCompanionView(model: model) }
    }
}
