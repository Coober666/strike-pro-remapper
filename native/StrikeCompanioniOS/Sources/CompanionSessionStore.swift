import Foundation
import StrikeSetlists

/// One bounded, atomically replaced app-owned snapshot. Never stores source URLs/bookmarks.
struct CompanionSessionStore {
    static let maximumBytes = 2 * Setlist.maximumBytes
    let url: URL

    static var live: Self {
        let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return Self(url: root.appendingPathComponent("StrikeCompanion/session-v1.json"))
    }

    struct Snapshot: Codable {
        var version = 1
        var document: Data?
        var selected: Int?
        var sourceName: String
        var isDemo: Bool
        var performanceMode: Bool
        var noteScale: Double
    }

    func load() throws -> Snapshot? {
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        let file = try FileHandle(forReadingFrom: url)
        defer { try? file.close() }
        let data = try file.read(upToCount: Self.maximumBytes + 1) ?? Data()
        guard data.count <= Self.maximumBytes else { throw SetlistError.invalid("Saved session is too large.") }
        let snapshot = try JSONDecoder().decode(Snapshot.self, from: data)
        try validate(snapshot)
        return snapshot
    }

    private func validate(_ snapshot: Snapshot) throws {
        guard snapshot.version == 1, [1.0, 1.3, 1.6].contains(snapshot.noteScale),
              snapshot.sourceName.count <= 255 else { throw SetlistError.invalid("Saved session is unsupported.") }
        if let document = snapshot.document { _ = try Setlist.decode(document) }
    }

    func save(_ snapshot: Snapshot) throws {
        try validate(snapshot)
        let data = try JSONEncoder().encode(snapshot)
        guard data.count <= Self.maximumBytes else { throw SetlistError.invalid("Saved session is too large.") }
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }

    static func documentData(_ document: Setlist) throws -> Data {
        let object: [String: Any] = ["format": "strike-setlist", "version": 1,
            "name": document.name, "notes": document.notes, "numbered": document.numbered,
            "entries": document.entries.map { ["kit": $0.kit, "song": $0.song, "output": $0.output, "notes": $0.notes] }]
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes])
        _ = try Setlist.decode(data)
        return data
    }
}
