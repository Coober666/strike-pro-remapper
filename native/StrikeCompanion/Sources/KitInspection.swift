import Foundation

/// Read-only interpretation of the known KIT / inst / str layout. No path resolution or writer.
public struct KitInspection: Sendable {
    public static let maximumBytes = 4 * 1_048_576
    public let originalData: Data
    public let header: Data
    public let pads: [KitPad]
    public let instruments: [String]
    public let tail: Data

    public func reference(_ index: Int) -> String {
        if index == 0xffff { return "Unassigned" }
        guard instruments.indices.contains(index) else { return "Unresolved string index \(index)" }
        return instruments[index]
    }

    public var unresolvedCount: Int {
        pads.reduce(0) { count, pad in count + [pad.layerA, pad.layerB].filter {
            $0 != 0xffff && !instruments.indices.contains($0)
        }.count }
    }

    public static func read(_ url: URL) throws -> Self {
        guard url.isFileURL else { throw SetlistError.invalid("Choose a kit file from Files.") }
        let access = url.startAccessingSecurityScopedResource()
        defer { if access { url.stopAccessingSecurityScopedResource() } }
        guard try url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile == true else {
            throw SetlistError.invalid("Choose a regular .skt file.")
        }
        let file = try FileHandle(forReadingFrom: url)
        defer { try? file.close() }
        return try decode(file.read(upToCount: maximumBytes + 1) ?? Data())
    }

    public static func decode(_ data: Data) throws -> Self {
        guard data.count <= maximumBytes else { throw SetlistError.invalid("Kit files must be 4 MiB or smaller.") }
        let bytes = [UInt8](data)
        var position = 0
        func has(_ magic: String) -> Bool {
            position + 4 <= bytes.count && Array(bytes[position..<position + 4]) == Array(magic.utf8)
        }
        func block(_ magic: String) throws -> Data {
            guard has(magic), bytes.count - position >= 8 else {
                throw SetlistError.invalid("Missing or truncated \(magic.trimmingCharacters(in: .whitespaces)) block.")
            }
            let size = (0..<4).reduce(0) { $0 | (Int(bytes[position + 4 + $1]) << ($1 * 8)) }
            guard size <= bytes.count - position - 8 else { throw SetlistError.invalid("A kit block extends past the end of the file.") }
            let start = position + 8
            position = start + size
            return Data(bytes[start..<position])
        }
        let kit = try block("KIT ")
        guard (44...4096).contains(kit.count) else { throw SetlistError.invalid("Unsupported kit header size.") }
        let header = data.prefix(position)
        var pads: [KitPad] = []
        while has("inst") {
            guard pads.count < 128 else { throw SetlistError.invalid("This kit has more than 128 pad zones.") }
            let payload = try block("inst")
            guard (62...4096).contains(payload.count), payload.prefix(4).allSatisfy({ (32...126).contains($0) }) else {
                throw SetlistError.invalid("Unsupported or truncated pad-zone data.")
            }
            let id = String(decoding: payload.prefix(4), as: UTF8.self).trimmingCharacters(in: .whitespaces)
            guard !id.isEmpty else { throw SetlistError.invalid("A pad zone has no identifier.") }
            pads.append(KitPad(id: id, payload: payload))
        }
        let strings = try block("str ")
        guard strings.isEmpty || strings.last == 0 else { throw SetlistError.invalid("The kit string table is not terminated.") }
        var instruments: [String] = []
        for raw in strings.split(separator: 0, omittingEmptySubsequences: true) {
            guard instruments.count < 4096, raw.count <= 240, raw.allSatisfy({ (32...126).contains($0) }) else {
                throw SetlistError.invalid("Unsupported kit string table (4096 references, 240 ASCII bytes each).")
            }
            // References are display text, even if they contain an absolute/traversal path.
            instruments.append(String(decoding: raw, as: UTF8.self))
        }
        return Self(originalData: data, header: Data(header), pads: pads, instruments: instruments,
                    tail: Data(bytes[position...]))
    }
}

public struct KitPad: Sendable {
    public let id: String
    public let payload: Data
    public var layerA: Int { word(4) }
    public var layerB: Int { word(24) }
    public var label: String { Self.labels[id] ?? id }
    public func byte(_ offset: Int) -> Int { Int(payload[offset]) }
    public func signed(_ offset: Int) -> Int { Int(Int8(bitPattern: payload[offset])) }
    private func word(_ offset: Int) -> Int { byte(offset) | byte(offset + 1) << 8 }

    private static let labels = [
        "K1H": "Kick 1 Head", "K2H": "Kick 2 Head", "S1H": "Snare Head", "S1R": "Snare Rim",
        "T1H": "Tom 1 Head", "T1R": "Tom 1 Rim", "T2H": "Tom 2 Head", "T2R": "Tom 2 Rim",
        "T3H": "Tom 3 Head", "T3R": "Tom 3 Rim", "T4H": "Tom 4 Head", "T4R": "Tom 4 Rim",
        "H1B": "Hi-Hat Bow", "H1E": "Hi-Hat Edge", "H1F": "Hi-Hat Foot",
        "C1B": "Cymbal 1 Bow", "C1E": "Cymbal 1 Edge", "C2B": "Cymbal 2 Bow", "C2E": "Cymbal 2 Edge",
        "C3B": "Cymbal 3 Bow", "C3E": "Cymbal 3 Edge", "R1D": "Ride Bell", "R1B": "Ride Bow", "R1E": "Ride Edge"
    ]
}
