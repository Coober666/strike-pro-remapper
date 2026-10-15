import AppKit
import SwiftUI
import UniformTypeIdentifiers

@MainActor
final class CompanionModel: ObservableObject {
    @Published var session = SetlistSession()
    @Published var isDemo = false
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var sourceName = ""
    @Published var query = ""
    @Published var performanceMode = false
    @Published var noteSize = 22.0
    @Published var isChoosingFile = false

    func showDemo() {
        guard !isLoading && !isChoosingFile else { return }
        do {
            guard let url = Bundle.main.url(forResource: "Demo.setlist", withExtension: "json") else {
                throw SetlistError.invalid("The demo is missing from this app. Rebuild the app bundle.")
            }
            session.open(try Setlist.read(url))
            query = ""
            isDemo = true
            sourceName = "Demo setlist"
        } catch { errorMessage = error.localizedDescription }
    }

    func chooseFile() {
        guard !isLoading && !isChoosingFile else { return }
        isChoosingFile = true
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = "Choose a JSON file exported from Strike’s Setlist Builder."
        panel.prompt = "Open setlist"
        panel.begin { [weak self] response in
            guard let self else { return }
            self.isChoosingFile = false
            if response == .OK, let url = panel.url { self.open(url) }
        }
    }

    func open(_ url: URL) {
        guard !isLoading && !isChoosingFile else { return }
        isLoading = true
        Task {
            defer { isLoading = false }
            do {
                let document = try await Task.detached { try Setlist.read(url) }.value
                session.open(document)
                query = ""
                sourceName = url.lastPathComponent
                isDemo = false
            } catch {
                errorMessage = "Couldn’t open this setlist. \(error.localizedDescription) Your current setlist is unchanged."
            }
        }
    }
}

private enum Theme {
    static let background = Color(red: 0.11, green: 0.13, blue: 0.15)
    static let sheet = Color(red: 0.15, green: 0.17, blue: 0.20)
    static let brass = Color(red: 0.85, green: 0.72, blue: 0.43)
}

struct CompanionView: View {
    @ObservedObject var model: CompanionModel

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Image(systemName: "music.note.list").font(.title2).foregroundStyle(Theme.brass)
                Text("Strike Companion").font(.headline)
                Spacer()
                if model.isLoading { ProgressView().controlSize(.small) }
                Button("Try demo", action: model.showDemo).disabled(model.isLoading || model.isChoosingFile)
                Button("Open setlist…", action: model.chooseFile).disabled(model.isLoading || model.isChoosingFile)
                    .buttonStyle(.borderedProminent).tint(Theme.brass)
            }
            .padding(18)
            Divider()
            if let document = model.session.document {
                HStack(spacing: 0) {
                    if !model.performanceMode {
                        sidebar(document)
                        Divider()
                    }
                    performanceSheet(document)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(Theme.sheet)
                }
            } else {
                VStack(alignment: .leading, spacing: 20) {
                    Image(systemName: "music.note.list").font(.system(size: 50)).foregroundStyle(Theme.brass)
                    Text("Your set, song by song.").font(.system(size: 34, weight: .semibold, design: .rounded))
                    Text("Keep the running order, kit references and performance notes in view.")
                        .font(.title3).foregroundStyle(.secondary)
                    Text("In Strike Remapper, open Setlist Builder and choose Export. Then open that JSON file here.")
                        .fixedSize(horizontal: false, vertical: true)
                    HStack {
                        Button("Open setlist…", action: model.chooseFile).buttonStyle(.borderedProminent).tint(Theme.brass)
                        Button("Explore the demo", action: model.showDemo)
                    }
                    Text("Reference viewer · kit files are not included in a setlist export.")
                        .font(.callout).foregroundStyle(.secondary)
                }
                .padding(40).frame(maxWidth: 680, maxHeight: .infinity, alignment: .leading)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            Divider()
            HStack {
                Text(model.isDemo ? "Demo · fictional songs and kit references" : (model.sourceName.isEmpty ? "Open a Strike setlist export to begin" : model.sourceName))
                    .lineLimit(1).truncationMode(.middle)
                Spacer()
                Text("Kit availability not checked").foregroundStyle(.secondary)
            }.font(.caption).padding(.horizontal, 18).padding(.vertical, 10)
        }
        .background(Theme.background).preferredColorScheme(.dark)
        .frame(minWidth: 780, minHeight: 540)
        .alert("Setlist couldn’t be opened", isPresented: Binding(
            get: { model.errorMessage != nil }, set: { if !$0 { model.errorMessage = nil } })) {
                Button("OK") { model.errorMessage = nil }
            } message: { Text(model.errorMessage ?? "") }
        .onOpenURL { model.open($0) }
    }

    private func sidebar(_ document: Setlist) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(document.name).font(.title2.bold()).fixedSize(horizontal: false, vertical: true)
            Text("\(document.entries.count) songs").foregroundStyle(.secondary)
            HStack {
                TextField("Search songs, kits or notes", text: $model.query).textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Search songs, kits, output labels and notes")
                if !model.query.isEmpty {
                    Button { model.query = "" } label: { Image(systemName: "xmark.circle.fill") }
                        .buttonStyle(.plain).accessibilityLabel("Clear search")
                }
            }
            ScrollView {
                LazyVStack(spacing: 4) {
                    ForEach(document.matchingIndices(model.query), id: \.self) { index in
                        let entry = document.entries[index]
                        Group {
                            Button { model.session.select(index) } label: {
                                HStack(alignment: .top, spacing: 12) {
                                    Text(String(format: "%02d", index + 1)).monospacedDigit().foregroundStyle(Theme.brass).frame(width: 26)
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(entry.title).fontWeight(.medium).multilineTextAlignment(.leading)
                                        Text(entry.kit).font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                                    }
                                    Spacer(minLength: 0)
                                }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                                    .background(model.session.selected == index ? Theme.brass.opacity(0.16) : .clear)
                                    .clipShape(RoundedRectangle(cornerRadius: 8))
                            }.buttonStyle(.plain)
                                .accessibilityLabel("Song \(index + 1): \(entry.title)")
                                .accessibilityValue("Kit: \(entry.kit)")
                                .accessibilityAddTraits(model.session.selected == index ? [.isSelected] : [])
                        }
                    }
                    if !model.query.isEmpty && document.matchingIndices(model.query).isEmpty {
                        Text("No matching songs").foregroundStyle(.secondary).padding()
                    }
                }
            }
        }.padding(18).frame(width: 280)
    }

    private func performanceSheet(_ document: Setlist) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Button { model.performanceMode.toggle() } label: {
                    Label(model.performanceMode ? "Show song list" : "Performance view",
                          systemImage: model.performanceMode ? "sidebar.left" : "arrow.up.left.and.arrow.down.right")
                }.keyboardShortcut("f", modifiers: [.command, .shift])
                    .accessibilityHint("Hides or shows the song list. Navigation keeps the original set order.")
                Spacer()
                Picker("Notes", selection: $model.noteSize) {
                    Text("Standard").tag(22.0)
                    Text("Large").tag(28.0)
                    Text("Extra large").tag(34.0)
                }.frame(width: 195).accessibilityLabel("Performance and show notes text size")
            }.padding(.horizontal, 20).padding(.vertical, 12)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    if let index = model.session.selected, document.entries.indices.contains(index) {
                        let entry = document.entries[index]
                        Text("Song \(index + 1) of \(document.entries.count)")
                            .font(.headline).foregroundStyle(Theme.brass)
                        Text(entry.title).font(.system(size: model.performanceMode ? 46 : 38, weight: .semibold, design: .rounded))
                            .accessibilityAddTraits(.isHeader)
                            .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Kit reference").accessibilityAddTraits(.isHeader).font(.headline).foregroundStyle(.secondary)
                            Text(entry.kit).font(.title3).textSelection(.enabled)
                            if !entry.output.isEmpty { Text("Output label: \(entry.output)").foregroundStyle(.secondary) }
                        }
                        Divider()
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Performance notes").accessibilityAddTraits(.isHeader).font(.headline).foregroundStyle(Theme.brass)
                            Text(entry.notes.isEmpty ? "No notes for this song." : entry.notes)
                                .font(.system(size: model.noteSize)).lineSpacing(7).textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    } else {
                        Text("No songs yet").font(.largeTitle.bold())
                        Text("Add songs in Strike’s Setlist Builder, export again, and open the updated file here.")
                            .foregroundStyle(.secondary)
                    }
                    if !document.notes.isEmpty {
                        Divider()
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Show notes").accessibilityAddTraits(.isHeader).font(.headline).foregroundStyle(.secondary)
                            Text(document.notes).font(.system(size: max(17, model.noteSize - 5))).lineSpacing(5).textSelection(.enabled)
                        }
                    }
                }.padding(32).frame(maxWidth: .infinity, alignment: .leading)
            }
            // A new song starts at its heading, even after scrolling long notes.
            .id(model.session.selected)
            Divider()
            HStack {
                Button { model.session.move(-1) } label: { Label("Previous", systemImage: "chevron.left") }
                    .accessibilityHint("Previous song in the original set order, regardless of search")
                    .keyboardShortcut(.leftArrow, modifiers: .command)
                    .disabled((model.session.selected ?? 0) == 0)
                Spacer()
                if let index = model.session.selected, index + 1 < document.entries.count {
                    Text("Next: \(document.entries[index + 1].title)").lineLimit(1).foregroundStyle(.secondary)
                }
                Spacer()
                Button { model.session.move(1) } label: { Label("Next", systemImage: "chevron.right") }
                    .accessibilityHint("Next song in the original set order, regardless of search")
                    .keyboardShortcut(.rightArrow, modifiers: .command)
                    .disabled(model.session.selected == nil || model.session.selected == document.entries.count - 1)
            }.controlSize(.large).padding(20)
        }
    }
}

struct StrikeCompanionApp: App {
    @StateObject private var model = CompanionModel()
    var body: some Scene {
        WindowGroup { CompanionView(model: model) }
            .defaultSize(width: 1080, height: 740)
            .commands { CommandGroup(replacing: .newItem) { Button("Open setlist…", action: model.chooseFile).keyboardShortcut("o") } }
    }
}

@main
enum CompanionMain {
    @MainActor static func main() throws {
        // Render only this app's synthetic demo, not the desktop or user documents.
        if CommandLine.arguments.count == 3, ["--render-demo", "--render-performance-demo"].contains(CommandLine.arguments[1]) {
            _ = NSApplication.shared
            let model = CompanionModel()
            model.showDemo()
            guard model.session.document != nil else { throw SetlistError.invalid("Demo failed to load.") }
            model.session.select(1)
            model.performanceMode = CommandLine.arguments[1] == "--render-performance-demo"
            if model.performanceMode { model.noteSize = 34 }
            let view = NSHostingView(rootView: CompanionView(model: model).frame(width: 1080, height: 740))
            view.frame = NSRect(x: 0, y: 0, width: 1080, height: 740)
            let window = NSWindow(contentRect: view.frame, styleMask: [.borderless], backing: .buffered, defer: false)
            window.contentView = view
            view.layoutSubtreeIfNeeded()
            guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else {
                throw SetlistError.invalid("Cannot render preview.")
            }
            view.cacheDisplay(in: view.bounds, to: bitmap)
            guard let data = bitmap.representation(using: .png, properties: [:]) else {
                throw SetlistError.invalid("Cannot encode preview.")
            }
            try data.write(to: URL(fileURLWithPath: CommandLine.arguments[2]), options: .withoutOverwriting)
        } else {
            StrikeCompanionApp.main()
        }
    }
}
