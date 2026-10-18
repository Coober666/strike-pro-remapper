import Foundation
import SwiftUI
import StrikeSetlists

@MainActor
final class MobileCompanionModel: ObservableObject {
    @Published private(set) var session = SetlistSession()
    @Published private(set) var sourceName = ""
    @Published private(set) var documentID = UUID()
    @Published private(set) var isDemo = false
    @Published private(set) var isLoading = false
    @Published var errorMessage: String?
    @Published var query = ""
    @Published var performanceMode = false { didSet { persist() } }
    @Published var noteScale = 1.0 { didSet { persist() } }
    @Published var choosingFile = false

    @Published private(set) var persistenceWarning: String?
    private let store: CompanionSessionStore?
    private var restoring = true

    init(store: CompanionSessionStore? = .live) {
        self.store = store
        defer { restoring = false }
        do {
            if let saved = try store?.load() {
                if let data = saved.document {
                    session.open(try Setlist.decode(data))
                    if let selected = saved.selected { session.select(selected) }
                    sourceName = saved.sourceName
                    isDemo = saved.isDemo
                }
                performanceMode = saved.performanceMode
                noteScale = saved.noteScale
            }
        } catch {
            persistenceWarning = "The saved session couldn’t be restored. Import your setlist again."
        }
    }

    func select(_ index: Int) { session.select(index); persist() }
    func move(_ delta: Int) { session.move(delta); persist() }

    func closeSetlist() {
        guard !isLoading && !choosingFile else { return }
        session = SetlistSession()
        sourceName = ""
        isDemo = false
        query = ""
        documentID = UUID()
        persist()
    }

    func persist() {
        guard !restoring, let store else { return }
        do {
            let data = try session.document.map { try CompanionSessionStore.documentData($0) }
            try store.save(.init(document: data, selected: session.selected, sourceName: String(sourceName.prefix(255)),
                isDemo: isDemo, performanceMode: performanceMode, noteScale: noteScale))
            persistenceWarning = nil
        } catch {
            persistenceWarning = "Changes couldn’t be saved on this device. Retry before closing the app; the previous saved session may return."
        }
    }

    func showDemo() {
        guard !isLoading && !choosingFile else { return }
        guard let url = Bundle.main.url(forResource: "Demo.setlist", withExtension: "json") else {
            errorMessage = "The bundled demo is missing. Rebuild the app."
            return
        }
        do { accept(try Setlist.read(url), source: "Demo setlist", demo: true) }
        catch { report(error) }
    }

    /// Read completely before replacing the session. Only one import may run at a time.
    func open(_ url: URL) async {
        guard !isLoading && !choosingFile else { return }
        guard url.isFileURL else {
            report(SetlistError.invalid("Choose a JSON file from Files."))
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            let document = try await Task.detached { try Setlist.read(url) }.value
            accept(document, source: url.lastPathComponent, demo: false)
        } catch { report(error) }
    }

    private func accept(_ document: Setlist, source: String, demo: Bool) {
        session.open(document)
        documentID = UUID()
        sourceName = source
        isDemo = demo
        query = ""
        errorMessage = nil
        persist()
    }

    func report(_ error: Error) {
        // Cancelling Files is an ordinary dismissal, not an import failure.
        if (error as NSError).domain == NSCocoaErrorDomain,
           (error as NSError).code == NSUserCancelledError { return }
        errorMessage = "Couldn’t open this setlist. \(error.localizedDescription) Your current setlist and song are unchanged."
    }
}
