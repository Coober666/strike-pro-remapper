import SwiftUI

@main
struct StrikeCompanionMobileApp: App {
    @StateObject private var model = MobileCompanionModel()
    var body: some Scene {
        WindowGroup { MobileCompanionView(model: model) }
    }
}
