import SwiftUI
import StrikeSetlists
import UniformTypeIdentifiers

@MainActor
final class KitInspectorModel: ObservableObject {
    @Published private(set) var kit: KitInspection?
    @Published private(set) var sourceName = ""
    @Published private(set) var isLoading = false
    @Published private(set) var documentID = UUID()
    @Published var selected = 0
    @Published var choosingFile = false
    @Published var errorMessage: String?

    func open(_ url: URL) async {
        guard !isLoading && !choosingFile else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let candidate = try await Task.detached { try KitInspection.read(url) }.value
            kit = candidate
            documentID = UUID()
            sourceName = url.lastPathComponent
            selected = 0
            errorMessage = nil
        } catch { report(error) }
    }

    func demo() async {
        guard let url = Bundle.main.url(forResource: "Demo", withExtension: "skt") else { return }
        await open(url)
    }

    func report(_ error: Error) {
        if (error as NSError).domain == NSCocoaErrorDomain,
           (error as NSError).code == NSUserCancelledError { return }
        errorMessage = "Couldn’t inspect this kit. \(error.localizedDescription) The current kit is unchanged."
    }
}

struct KitInspectorView: View {
    @ObservedObject var model: KitInspectorModel
    let close: () -> Void
    @State private var path: [Int] = []
    @Environment(\.horizontalSizeClass) private var sizeClass

    var body: some View {
        GeometryReader { geometry in
            let wide = sizeClass == .regular && geometry.size.width >= 760
            NavigationStack(path: $path) {
                Group {
                    if let kit = model.kit {
                        if wide {
                            HStack(spacing: 0) {
                                zones(kit, wide: true).frame(width: min(310, geometry.size.width * 0.32))
                                Divider()
                                detail(kit, index: model.selected)
                            }
                        } else { zones(kit, wide: false) }
                    } else { welcome }
                }
                .background(Stage.background)
                .navigationTitle(model.kit == nil ? "Kit inspector" : model.sourceName)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { controls }
                .navigationDestination(for: Int.self) { index in
                    if let kit = model.kit, kit.pads.indices.contains(index) {
                        detail(kit, index: index).navigationTitle(kit.pads[index].label)
                            .toolbar { controls }
                    }
                }
            }
        }
        .tint(Stage.brass).preferredColorScheme(.dark)
        .fileImporter(isPresented: $model.choosingFile,
                      allowedContentTypes: [UTType(filenameExtension: "skt") ?? .data]) { result in
            switch result {
            case .success(let url): Task { await model.open(url) }
            case .failure(let error): model.report(error)
            }
        }
        .onChange(of: model.documentID) { _, _ in path = [] }
        .alert("Kit couldn’t be opened", isPresented: Binding(
            get: { model.errorMessage != nil }, set: { if !$0 { model.errorMessage = nil } })) {
            Button("OK", role: .cancel) { model.errorMessage = nil }
        } message: { Text(model.errorMessage ?? "") }
    }

    @ToolbarContentBuilder
    private var controls: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Button("Done", action: close).frame(minHeight: 44)
                .accessibilityIdentifier("close-inspector")
                .disabled(model.isLoading || model.choosingFile)
        }
        ToolbarItem(placement: .topBarTrailing) {
            if model.isLoading { ProgressView() }
            else {
                Button("Open kit", systemImage: "folder") { model.choosingFile = true }
                    .labelStyle(.iconOnly).frame(minHeight: 44)
                    .accessibilityIdentifier("import-kit")
                    .disabled(model.choosingFile)
            }
        }
    }

    private var welcome: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Image(systemName: "circle.grid.3x3").font(.system(size: 48)).foregroundStyle(Stage.brass)
                Text("Look inside your kit.").font(.largeTitle.weight(.semibold))
                Text("Open a Strike .skt file to inspect its pad zones, Layer A/B references and stored settings.")
                    .font(.title3)
                Button("Open kit", systemImage: "folder") { model.choosingFile = true }
                    .buttonStyle(.borderedProminent).foregroundStyle(.black).frame(minHeight: 44)
                    .disabled(model.isLoading || model.choosingFile)
                Button("Try synthetic kit") { Task { await model.demo() } }
                    .frame(minHeight: 44).accessibilityIdentifier("kit-demo")
                    .disabled(model.isLoading || model.choosingFile)
                Text("Read-only inspection. Sound files aren’t included, references aren’t opened, and availability isn’t checked. There is no editing, playback or deployment.")
                    .font(.footnote).foregroundStyle(.secondary)
            }.padding(28).frame(maxWidth: 560, alignment: .leading).frame(maxWidth: .infinity)
        }
    }

    private func zones(_ kit: KitInspection, wide: Bool) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 8) {
                Text("\(kit.pads.count) pad zones").font(.title2.weight(.semibold))
                Text("Read-only · Sound availability not checked").font(.footnote).foregroundStyle(.secondary)
                if kit.unresolvedCount > 0 {
                    Text("\(kit.unresolvedCount) assignments have unresolved string indices.").font(.footnote).foregroundStyle(Stage.brass)
                }
            }.padding()
            List(kit.pads.indices, id: \.self) { index in
                let pad = kit.pads[index]
                Group {
                    if wide {
                        Button { model.selected = index } label: { zoneLabel(pad) }
                            .accessibilityAddTraits(model.selected == index ? [.isSelected] : [])
                    } else {
                        NavigationLink(value: index) { zoneLabel(pad) }
                    }
                }.accessibilityIdentifier("kit-zone-\(pad.id)")
                    .listRowBackground(wide && model.selected == index ? Stage.brass.opacity(0.14) : Stage.background)
            }.listStyle(.plain).scrollContentBackground(.hidden)
            if kit.pads.isEmpty { Text("This kit has no pad zones.").padding() }
        }
    }

    private func zoneLabel(_ pad: KitPad) -> some View {
        HStack(spacing: 12) {
            Text(pad.id).font(.system(.caption, design: .monospaced)).foregroundStyle(Stage.brass).frame(width: 38)
            Text(pad.label).foregroundStyle(.primary)
        }.frame(minHeight: 44, alignment: .leading)
    }

    private func detail(_ kit: KitInspection, index: Int) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                if kit.pads.indices.contains(index) {
                    let pad = kit.pads[index]
                    Text(pad.label).font(.largeTitle.weight(.semibold)).accessibilityIdentifier("kit-pad-title")
                    Text("\(pad.id) · Stored kit settings").font(.subheadline).foregroundStyle(.secondary)
                    Text("Read-only. Sound availability not checked.").font(.footnote).foregroundStyle(.secondary)
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 260), alignment: .topLeading)], alignment: .leading, spacing: 24) {
                        layer(kit, pad: pad, name: "Layer A", offset: 0, reference: pad.layerA)
                        layer(kit, pad: pad, name: "Layer B", offset: 20, reference: pad.layerB)
                    }
                    Divider()
                    Text("Zone settings").font(.title2.weight(.semibold)).foregroundStyle(Stage.brass)
                    values([
                        ("MIDI channel", String(pad.byte(51) + 1)), ("MIDI note", String(pad.byte(52))),
                        ("Reverb send", String(pad.byte(44))), ("FX1 send", String(pad.byte(45))),
                        ("FX2 send", String(pad.byte(61))), ("Mute group", String(pad.byte(49))),
                        ("Priority", option(pad.byte(48), ["Low", "Medium", "High"])),
                        ("Note Off", option(pad.byte(50), ["Sent", "None", "Alt"])),
                        ("Playback", option(pad.byte(54), ["Mono", "Poly"]))
                    ])
                    Divider()
                    Text("References are text from this kit. No instruments, samples or cards have been opened.")
                        .font(.footnote).foregroundStyle(.secondary)
                } else { Text("Select a pad zone.").font(.title2) }
            }.padding(28).frame(maxWidth: 860, alignment: .leading).frame(maxWidth: .infinity, alignment: .topLeading)
        }.id("\(model.sourceName)-\(index)").background(Stage.sheet)
    }

    private func layer(_ kit: KitInspection, pad: KitPad, name: String, offset: Int, reference: Int) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(name).font(.title2.weight(.semibold)).foregroundStyle(Stage.brass)
            Text(kit.reference(reference)).font(.headline).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier(offset == 0 ? "kit-layer-a" : "kit-layer-b")
            values([
                ("Level", String(pad.byte(6 + offset))), ("Pan", String(pad.signed(7 + offset))),
                ("Decay", String(pad.byte(8 + offset))), ("Pitch", "\(pad.signed(11 + offset)) st"),
                ("Fine pitch", "\(pad.signed(12 + offset)) cents"),
                ("Velocity range", "\(pad.byte(19 + offset))–\(pad.byte(20 + offset))"),
                ("Filter cutoff", String(pad.byte(13 + offset))),
                ("Filter", option(pad.byte(14 + offset), ["Off", "On"])),
                ("Loop", option(pad.byte(21 + offset), ["Off", "On"]))
            ])
        }.frame(maxWidth: .infinity, alignment: .topLeading)
    }

    private func option(_ value: Int, _ names: [String]) -> String {
        names.indices.contains(value) ? names[value] : "Unknown (\(value))"
    }

    private func values(_ rows: [(String, String)]) -> some View {
        VStack(spacing: 10) {
            ForEach(rows, id: \.0) { label, value in
                LabeledContent(label) { Text(value).foregroundStyle(.primary).textSelection(.enabled) }
            }
        }
    }
}
