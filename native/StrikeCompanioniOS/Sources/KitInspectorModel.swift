import Foundation
import StrikeSetlists

@MainActor
final class KitInspectorModel: ObservableObject {
    @Published private(set) var session: KitEditingSession?
    var kit: KitInspection? { session?.current }
    var isDirty: Bool { session?.isDirty == true }
    @Published private(set) var sourceName = ""
    @Published private(set) var isLoading = false
    @Published private(set) var isExporting = false
    @Published private(set) var documentID = UUID()
    @Published var selected = 0
    @Published var choosingFile = false
    @Published var choosingExportFolder = false
    @Published var errorMessage: String?
    @Published private(set) var errorTitle = "Kit couldn’t be opened"
    @Published var exportMessage: String?
    @Published private(set) var pendingImport: PendingImport?
    struct PendingImport { let kit: KitInspection; let name: String }
    var busy: Bool { isLoading || isExporting || choosingFile || choosingExportFolder || pendingImport != nil }

    func open(_ url: URL) async {
        guard !busy else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let candidate = try await Task.detached { try KitInspection.read(url) }.value
            let pending = PendingImport(kit: candidate, name: url.lastPathComponent)
            errorMessage = nil
            if isDirty { pendingImport = pending }
            else { accept(pending) }
        } catch { report(error) }
    }
    func confirmReplacement() {
        guard let pending = pendingImport else { return }
        pendingImport = nil
        accept(pending)
    }
    func cancelReplacement() { pendingImport = nil }
    private func accept(_ pending: PendingImport) {
        session = KitEditingSession(pending.kit)
        documentID = UUID()
        sourceName = pending.name
        selected = 0
        exportMessage = nil
    }
    func demo() async {
        guard let url = Bundle.main.url(forResource: "Demo", withExtension: "skt") else { return }
        await open(url)
    }
    func edit(_ parameter: KitParameter, value: Int, pad: Int) -> Bool {
        mutate { try $0.set(parameter, value: value, pad: pad) }
    }
    func assign(_ reference: Int, layer: Int, pad: Int) -> Bool {
        mutate { try $0.assign(reference, layer: layer, pad: pad) }
    }
    func undo() { _ = mutate { try $0.undo() } }
    func redo() { _ = mutate { try $0.redo() } }
    private func mutate(_ operation: (inout KitEditingSession) throws -> Void) -> Bool {
        guard !busy, var candidate = session else { return false }
        do {
            try operation(&candidate)
            session = candidate
            exportMessage = nil
            return true
        } catch {
            errorTitle = "Edit couldn’t be applied"
            errorMessage = error.localizedDescription
            return false
        }
    }
    func chooseExportFolder() {
        guard !busy else { return }
        // Optional local convenience; other Files providers remain usable if it cannot be prepared.
        if let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first {
            try? FileManager.default.createDirectory(at: documents.appendingPathComponent("Kit Copies"),
                                                     withIntermediateDirectories: true)
        }
        choosingExportFolder = true
    }

    func export(to folder: URL) async {
        guard !busy, let data = kit?.encoded() else { return }
        isExporting = true
        errorMessage = nil
        exportMessage = nil
        defer { isExporting = false }
        do {
            let url = try await Task.detached { try KitCopyExporter.copy(data, to: folder) }.value
            exportMessage = "Created \(url.lastPathComponent) in the selected folder. Your original is untouched."
        } catch {
            if isCancellation(error) { return }
            errorTitle = "Copy couldn’t be exported"
            errorMessage = "Copy couldn’t be exported. \(error.localizedDescription) Your edits are still open. Check the destination before trying again."
        }
    }
    func report(_ error: Error) {
        if isCancellation(error) { return }
        errorTitle = "Kit couldn’t be opened"
        errorMessage = "Couldn’t open this kit. \(error.localizedDescription) The current kit is unchanged."
    }
    private func isCancellation(_ error: Error) -> Bool {
        (error as NSError).domain == NSCocoaErrorDomain && (error as NSError).code == NSUserCancelledError
    }
}
