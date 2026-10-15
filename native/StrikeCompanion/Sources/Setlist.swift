import Foundation
import CoreFoundation

enum SetlistError: LocalizedError {
    case invalid(String)
    var errorDescription: String? {
        switch self { case .invalid(let message): return message }
    }
}

struct SetlistEntry: Equatable, Sendable {
    let kit: String
    let song: String
    let output: String
    let notes: String
    var title: String { song.isEmpty ? String(kit.split(separator: "/").last ?? "Kit") : song }
}

struct Setlist: Equatable, Sendable {
    static let maximumBytes = 1_048_576
    let name: String
    let notes: String
    let numbered: Bool
    let entries: [SetlistEntry]

    static func text(_ value: Any?, label: String, limit: Int, required: Bool = false) throws -> String {
        guard let value = value as? String, value.unicodeScalars.count <= limit,
              !value.unicodeScalars.contains(where: { $0.value < 32 && $0.value != 9 && $0.value != 10 }) else {
            throw SetlistError.invalid("\(label) must be text of at most \(limit) characters.")
        }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !required || !trimmed.isEmpty else { throw SetlistError.invalid("\(label) is required.") }
        return trimmed
    }

    static func decode(_ data: Data) throws -> Setlist {
        guard data.count <= maximumBytes else { throw SetlistError.invalid("Setlists must be 1 MiB or smaller.") }
        guard String(data: data, encoding: .utf8) != nil else { throw SetlistError.invalid("Choose a UTF-8 JSON setlist exported by Strike.") }
        let raw: Any
        do { raw = try JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed]) }
        catch { throw SetlistError.invalid("This file is not valid JSON. Export the setlist again from Strike.") }
        guard let object = raw as? [String: Any], object["format"] as? String == "strike-setlist",
              let version = object["version"] as? NSNumber,
              CFGetTypeID(version) != CFBooleanGetTypeID(),
              !["d", "f"].contains(String(cString: version.objCType)), version.intValue == 1 else {
            throw SetlistError.invalid("Choose a Strike setlist JSON file (version 1).")
        }
        guard let numbered = object["numbered"] as? NSNumber,
              CFGetTypeID(numbered) == CFBooleanGetTypeID() else {
            throw SetlistError.invalid("Numbered filenames must be on or off.")
        }
        guard let rows = object["entries"] as? [Any], rows.count <= 128 else {
            throw SetlistError.invalid("A setlist holds up to 128 songs.")
        }
        let name = try text(object["name"], label: "Setlist name", limit: 80, required: true)
        let notes = try text(object["notes"] ?? "", label: "Show notes", limit: 2000)
        let entries = try rows.map { value -> SetlistEntry in
            guard let row = value as? [String: Any] else { throw SetlistError.invalid("Each song needs a kit reference.") }
            let kit = try text(row["kit"], label: "Kit reference", limit: 240, required: true)
            let parts = kit.components(separatedBy: "/")
            guard !parts.contains(where: { $0.isEmpty || $0 == "." || $0 == ".." }),
                  !kit.contains(where: { "\\:*?\"<>|".contains($0) }),
                  !kit.unicodeScalars.contains(where: { $0.value < 32 }),
                  kit.lowercased().hasSuffix(".skt"), !kit.lowercased().hasSuffix(".autosave.skt") else {
                throw SetlistError.invalid("Kit references must name saved .skt files inside the library kits folder.")
            }
            return SetlistEntry(kit: kit,
                song: try text(row["song"] ?? "", label: "Song title", limit: 100),
                output: try text(row["output"] ?? "", label: "Output name", limit: 100),
                notes: try text(row["notes"] ?? "", label: "Song notes", limit: 500))
        }
        return Setlist(name: name, notes: notes, numbered: numbered.boolValue, entries: entries)
    }

    static func read(_ url: URL) throws -> Setlist {
        let access = url.startAccessingSecurityScopedResource()
        defer { if access { url.stopAccessingSecurityScopedResource() } }
        let info = try url.resourceValues(forKeys: [.isRegularFileKey])
        guard info.isRegularFile == true else { throw SetlistError.invalid("Choose a regular JSON file.") }
        let file = try FileHandle(forReadingFrom: url)
        defer { try? file.close() }
        return try decode(file.read(upToCount: maximumBytes + 1) ?? Data())
    }
}

struct SetlistSession {
    private(set) var document: Setlist?
    private(set) var selected: Int?
    mutating func open(_ document: Setlist) {
        self.document = document
        selected = document.entries.isEmpty ? nil : 0
    }
    mutating func importData(_ data: Data) throws { open(try Setlist.decode(data)) }
    mutating func select(_ index: Int) {
        guard let document, document.entries.indices.contains(index) else { return }
        selected = index
    }
    mutating func move(_ delta: Int) {
        guard let selected, let count = document?.entries.count, count > 0 else { return }
        // Only single-step navigation is exposed, avoiding overflow from arbitrary offsets.
        if delta == 1 && selected < count - 1 { self.selected = selected + 1 }
        if delta == -1 && selected > 0 { self.selected = selected - 1 }
    }
}
