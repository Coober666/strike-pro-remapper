// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "StrikeSetlists",
    platforms: [.macOS(.v14), .iOS(.v16)],
    products: [.library(name: "StrikeSetlists", targets: ["StrikeSetlists"])],
    targets: [
        .target(name: "StrikeSetlists", path: "Sources", exclude: ["StrikeCompanion.swift"], sources: ["Setlist.swift", "KitInspection.swift", "KitEditing.swift"]),
        .executableTarget(name: "core-probe", dependencies: ["StrikeSetlists"], path: "PackageProbe")
    ]
)
