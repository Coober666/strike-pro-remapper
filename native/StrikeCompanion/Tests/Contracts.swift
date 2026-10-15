import Foundation

struct ContractCase: Decodable { let name: String; let json: String; let valid: Bool }

@main
enum Contracts {
    static func require(_ condition: Bool, _ message: String) throws {
        if !condition { throw SetlistError.invalid("FAILED: \(message)") }
    }
    static func main() throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        let cases = try JSONDecoder().decode([ContractCase].self,
            from: Data(contentsOf: root.appendingPathComponent("Tests/Cases.json")))
        var count = 0
        for item in cases {
            let accepted = (try? Setlist.decode(Data(item.json.utf8))) != nil
            try require(accepted == item.valid, item.name)
            count += 1
        }
        let demoURL = root.appendingPathComponent("Resources/Demo.setlist.json")
        let original = try Data(contentsOf: demoURL)
        let demo = try Setlist.read(demoURL)
        try require(demo.entries.count == 4 && demo.entries[1].song == "Paper Satellites", "demo order")
        var session = SetlistSession()
        session.open(demo)
        try require(session.selected == 0, "opening selects first song")
        session.move(-1)
        try require(session.selected == 0, "previous clamps at start")
        session.move(1)
        try require(session.selected == 1, "next selects second song")
        session.select(999)
        try require(session.selected == 1, "invalid selection ignored")
        var rejected = false
        do { try session.importData(Data("invalid".utf8)) }
        catch { rejected = true }
        try require(rejected && session.document == demo && session.selected == 1,
                    "failed import preserves document and selection")
        session.select(demo.entries.count - 1)
        session.move(1)
        try require(session.selected == demo.entries.count - 1, "next clamps at end")
        session.open(Setlist(name: "Empty", notes: "", numbered: false, entries: []))
        session.move(1)
        try require(session.selected == nil, "empty set has no selection")
        try require((try? Setlist.decode(Data(repeating: 32, count: Setlist.maximumBytes + 1))) == nil, "byte bound")
        try require((try? Setlist.decode(Data([0xFF]))) == nil, "invalid UTF-8")
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: temp) }
        let oversized = temp.appendingPathComponent("oversized.json")
        try Data(repeating: 32, count: Setlist.maximumBytes + 1).write(to: oversized)
        try require((try? Setlist.read(oversized)) == nil, "bounded file reading")
        try require((try? Setlist.read(temp)) == nil, "directory cannot be imported")
        try require((try? Setlist.read(temp.appendingPathComponent("missing.json"))) == nil, "missing file rejected")
        try require(try Data(contentsOf: demoURL) == original, "opening preserves source bytes")
        print("PASS: \(count) format cases plus navigation, preservation, file reading and byte bounds")
    }
}
