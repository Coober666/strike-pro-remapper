import Foundation
import StrikeSetlists

// A separate consumer proves the public library works without AppKit or SwiftUI.
let document = try Setlist.read(URL(fileURLWithPath: CommandLine.arguments[1]))
precondition(document.entries.count == 4)
precondition(document.matchingIndices("satellites") == [1])
var session = SetlistSession()
session.open(document)
session.move(1)
precondition(session.selected == 1 && session.document == document)
print("PASS: independent StrikeSetlists library consumer")
