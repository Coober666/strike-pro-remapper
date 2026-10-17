import SwiftUI
import StrikeSetlists
import UniformTypeIdentifiers

private enum Stage {
    static let background = Color(red: 0.11, green: 0.13, blue: 0.15)
    static let sheet = Color(red: 0.15, green: 0.17, blue: 0.20)
    static let brass = Color(red: 0.85, green: 0.72, blue: 0.43)
}

struct MobileCompanionView: View {
    @ObservedObject var model: MobileCompanionModel
    @State private var showingSongs = false
    @State private var showingImportError = false
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @ScaledMetric(relativeTo: .title3) private var noteSize = 22.0

    var body: some View {
        GeometryReader { geometry in
            let wide = horizontalSizeClass == .regular && geometry.size.width >= 760
            NavigationStack {
                Group {
                    if let document = model.session.document {
                        HStack(spacing: 0) {
                            if wide && !model.performanceMode {
                                songList(document, dismissOnSelect: false)
                                    .frame(width: min(320, geometry.size.width * 0.33))
                                Divider()
                            }
                            sheet(document, wide: wide)
                        }
                    } else { welcome }
                }
                .background(Stage.background)
                .navigationTitle(model.session.document?.name ?? "Strike Companion")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    if model.session.document != nil && (!wide || model.performanceMode) {
                        ToolbarItem(placement: .topBarLeading) {
                            Button { showingSongs = true } label: { Image(systemName: "list.bullet") }
                                .frame(minWidth: 44, minHeight: 44)
                                .accessibilityLabel("Songs").accessibilityIdentifier("songs")
                        }
                    }
                    ToolbarItemGroup(placement: .topBarTrailing) {
                        if model.isLoading { ProgressView().accessibilityLabel("Opening setlist") }
                        Button { model.choosingFile = true } label: { Image(systemName: "folder") }
                            .frame(minWidth: 44, minHeight: 44)
                            .accessibilityLabel("Import setlist").accessibilityIdentifier("import")
                            .disabled(model.isLoading || model.choosingFile)
                            .keyboardShortcut("o", modifiers: .command)
                        if model.session.document != nil { displayMenu }
                    }
                }
            }
            .tint(Stage.brass)
            .sheet(isPresented: $showingSongs) {
                if let document = model.session.document {
                    NavigationStack {
                        songList(document, dismissOnSelect: true)
                            .navigationTitle("Running order")
                            .navigationBarTitleDisplayMode(.inline)
                            .toolbar { ToolbarItem(placement: .confirmationAction) {
                                Button("Done") { showingSongs = false }.frame(minHeight: 44)
                            } }
                    }.tint(Stage.brass).preferredColorScheme(.dark)
                }
            }
        }
        .preferredColorScheme(.dark)
        .fileImporter(isPresented: $model.choosingFile, allowedContentTypes: [.json]) { result in
            switch result {
            case .success(let url): Task { await model.open(url) }
            case .failure(let error): model.report(error)
            }
        }
        .onOpenURL { url in Task { await model.open(url) } }
        .onChange(of: model.errorMessage) { _, message in showingImportError = message != nil }
        .alert("Setlist couldn’t be opened", isPresented: $showingImportError) {
            Button("OK", role: .cancel) { model.errorMessage = nil }
        } message: { Text(model.errorMessage ?? "") }
    }

    private var welcome: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Image(systemName: "music.note.list").font(.system(size: 52)).foregroundStyle(Stage.brass)
                Text("Your set,\nsong by song.").font(.system(.largeTitle, design: .rounded).weight(.semibold))
                    .accessibilityAddTraits(.isHeader)
                Text("Keep your running order, kit references and performance notes close at hand.")
                    .font(.title3).foregroundStyle(.secondary)
                Text("In Strike Remapper, open Setlist Builder and choose Export JSON. Save the file to Files, then import it here.")
                Button { model.choosingFile = true } label: {
                    Label("Import setlist", systemImage: "folder").frame(maxWidth: .infinity, minHeight: 44)
                }.buttonStyle(.borderedProminent).tint(Stage.brass).foregroundStyle(.black)
                    .disabled(model.isLoading || model.choosingFile)
                Button("Try demo", action: model.showDemo).frame(minHeight: 44)
                    .accessibilityIdentifier("demo").disabled(model.isLoading || model.choosingFile)
                Text("A setlist contains references and notes. Kit files are not included, and kit availability is not checked.")
                    .font(.footnote).foregroundStyle(.secondary)
            }.padding(28).frame(maxWidth: 560, alignment: .leading).frame(maxWidth: .infinity)
        }
    }

    private var displayMenu: some View {
        Menu("Reading options", systemImage: "textformat.size") {
            Button { model.performanceMode.toggle() } label: {
                Label(model.performanceMode ? "Leave performance view" : "Performance view", systemImage: "arrow.up.left.and.arrow.down.right")
            }.accessibilityIdentifier("performance")
            Picker("Notes size", selection: $model.noteScale) {
                Text("Standard").tag(1.0)
                Text("Large").tag(1.3)
                Text("Extra large").tag(1.6)
            }
            Button("Try demo", action: model.showDemo).disabled(model.isLoading || model.choosingFile)
        }
            .labelStyle(.iconOnly)
            .frame(minWidth: 44, minHeight: 44)
            .accessibilityLabel("Reading options").accessibilityIdentifier("reading-options")
    }

    private func songList(_ document: Setlist, dismissOnSelect: Bool) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("\(document.entries.count) songs").font(.subheadline).foregroundStyle(.secondary).padding(.horizontal)
            List {
                ForEach(document.matchingIndices(model.query), id: \.self) { index in
                    Button {
                        model.select(index)
                        if dismissOnSelect { showingSongs = false }
                    } label: {
                        HStack(alignment: .top, spacing: 12) {
                            Text(String(format: "%02d", index + 1)).monospacedDigit().foregroundStyle(Stage.brass)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(document.entries[index].title).fontWeight(.medium)
                                Text(document.entries[index].kit).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer(minLength: 0)
                            if model.session.selected == index { Image(systemName: "checkmark").foregroundStyle(Stage.brass) }
                        }.padding(.vertical, 8).frame(minHeight: 44, alignment: .leading).contentShape(Rectangle())
                    }.buttonStyle(.plain)
                        .accessibilityLabel("Song \(index + 1): \(document.entries[index].title)")
                        .accessibilityIdentifier("song-\(index)")
                        .accessibilityAddTraits(model.session.selected == index ? [.isSelected] : [])
                        .listRowBackground(model.session.selected == index ? Stage.brass.opacity(0.12) : Stage.background)
                }
                if document.matchingIndices(model.query).isEmpty {
                    Text(document.entries.isEmpty ? "No songs yet" : "No matching songs").foregroundStyle(.secondary)
                }
            }.listStyle(.plain).scrollContentBackground(.hidden)
                .searchable(text: $model.query, placement: .sidebar, prompt: "Search songs, kits or notes")
                .accessibilityIdentifier("running-order")
        }.background(Stage.background)
    }

    private func sheet(_ document: Setlist, wide: Bool) -> some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    if let index = model.session.selected, document.entries.indices.contains(index) {
                        let entry = document.entries[index]
                        Text("Song \(index + 1) of \(document.entries.count)").font(.headline).foregroundStyle(Stage.brass)
                            .accessibilityIdentifier("song-position")
                        Text(entry.title).font(.system(wide ? .largeTitle : .title, design: .rounded).weight(.semibold))
                            .accessibilityAddTraits(.isHeader).accessibilityIdentifier("song-title")
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Kit reference").font(.subheadline).foregroundStyle(.secondary)
                            Text(entry.kit).font(.headline).textSelection(.enabled)
                            if !entry.output.isEmpty { Text("Output label: \(entry.output)").foregroundStyle(.secondary) }
                        }
                        Divider()
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Performance notes").font(.headline).foregroundStyle(Stage.brass).accessibilityAddTraits(.isHeader)
                            Text(entry.notes.isEmpty ? "No notes for this song." : entry.notes)
                                .font(.system(size: noteSize * model.noteScale)).lineSpacing(6).textSelection(.enabled)
                                .accessibilityIdentifier("performance-notes")
                        }
                    } else {
                        Text("No songs yet").font(.largeTitle.bold()).accessibilityAddTraits(.isHeader)
                        Text("Add songs in Setlist Builder, export again, then import the updated file.")
                    }
                    if !document.notes.isEmpty {
                        Divider()
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Show notes").font(.headline).foregroundStyle(Stage.brass).accessibilityAddTraits(.isHeader)
                            Text(document.notes).font(.system(size: max(17, noteSize * model.noteScale - 5)))
                                .lineSpacing(5).textSelection(.enabled)
                        }
                    }
                    Divider()
                    Text(model.isDemo ? "Demo · fictional songs and kit references" : model.sourceName)
                    Text("Kit availability not checked").font(.caption)
                }.frame(maxWidth: 760, alignment: .leading)
                    .padding(wide ? 32 : 24).frame(maxWidth: .infinity, alignment: .topLeading)
            }.id("\(model.documentID)-\(model.session.selected ?? -1)")
                .accessibilityIdentifier("song-sheet")
            Divider()
            navigation(document)
        }.background(Stage.sheet)
    }

    private func navigation(_ document: Setlist) -> some View {
        VStack(spacing: 8) {
            if let index = model.session.selected, index + 1 < document.entries.count {
                Text("Next: \(document.entries[index + 1].title)").font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            HStack(spacing: 20) {
                Button { model.move(-1) } label: {
                    Label("Previous", systemImage: "chevron.left").frame(maxWidth: .infinity, minHeight: 48)
                }.disabled((model.session.selected ?? 0) == 0).accessibilityIdentifier("previous")
                    .keyboardShortcut(.leftArrow, modifiers: .command)
                Button { model.move(1) } label: {
                    Label("Next", systemImage: "chevron.right").frame(maxWidth: .infinity, minHeight: 48)
                }.disabled(model.session.selected == nil || model.session.selected == document.entries.count - 1)
                    .accessibilityIdentifier("next").keyboardShortcut(.rightArrow, modifiers: .command)
            }.buttonStyle(.bordered)
        }.padding(.horizontal, 20).padding(.vertical, 12)
    }
}
