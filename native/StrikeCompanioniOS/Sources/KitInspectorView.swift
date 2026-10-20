import SwiftUI
import StrikeSetlists
import UniformTypeIdentifiers

struct KitInspectorView: View {
    @ObservedObject var model: KitInspectorModel
    let close: () -> Void
    @State private var path: [Int] = []
    @State private var editing: KitEditRequest?
    @State private var showReplacementConfirmation = false
    @State private var exportingFolder = false
    @State private var showDrumMap = false
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.dynamicTypeSize) private var typeSize
    private var usingDrumMap: Bool { showDrumMap && !typeSize.isAccessibilitySize }

    var body: some View {
        GeometryReader { geometry in
            let wide = sizeClass == .regular && geometry.size.width >= 760
            NavigationStack(path: $path) {
                Group {
                    if let kit = model.kit {
                        if wide {
                            HStack(spacing: 0) {
                                zones(kit, wide: true).frame(width: usingDrumMap ? min(560, geometry.size.width * 0.48) : min(310, geometry.size.width * 0.32))
                                Divider()
                                detail(kit, index: model.selected, wide: wide)
                            }
                        } else { zones(kit, wide: false) }
                    } else { welcome }
                }
                .background(Stage.background)
                .navigationTitle(model.kit == nil ? "Kit editor" : model.sourceName)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { controls }
                .navigationDestination(for: Int.self) { index in
                    if let kit = model.kit, kit.pads.indices.contains(index) {
                        detail(kit, index: index, wide: wide).navigationTitle(kit.pads[index].label)
                            .toolbar { controls }
                    }
                }
            }
            .onChange(of: wide) { _, wide in
                // A compact detail destination must not cover the new side-by-side workspace.
                if wide { path = [] }
            }
        }
        .tint(Stage.brass).preferredColorScheme(.dark)
        // One presenter serves both operations, including on older SwiftUI releases.
        .fileImporter(isPresented: Binding(
            get: { model.choosingFile || model.choosingExportFolder },
            set: { if !$0 { model.choosingFile = false; model.choosingExportFolder = false } }),
                      allowedContentTypes: exportingFolder ? [.folder] : [UTType(filenameExtension: "skt") ?? .data]) { result in
            let exportCopy = exportingFolder
            switch result {
            case .success(let url):
                Task {
                    if exportCopy { await model.export(to: url) }
                    else { await model.open(url) }
                }
            case .failure(let error):
                if exportCopy { model.reportExportFailure(error) }
                else { model.report(error) }
            }
        }
        .sheet(item: $editing, onDismiss: {
            if model.pendingImport != nil { showReplacementConfirmation = true }
        }) { request in
            if let kit = model.kit, request.documentID == model.documentID {
                KitEditSheet(request: request, kit: kit) { value in
                    guard request.documentID == model.documentID else { return false }
                    if let parameter = request.parameter {
                        return model.edit(parameter, value: value, pad: request.pad)
                    }
                    return model.assign(value, layer: request.layer!, pad: request.pad)
                }
            }
        }
        .onChange(of: path) { _, path in if let index = path.last { model.selected = index } }
        .onChange(of: model.documentID) { _, _ in path = []; editing = nil }
        .onChange(of: model.pendingImport != nil, initial: true) { _, pending in
            if pending && editing != nil { editing = nil }
            else { showReplacementConfirmation = pending }
        }
        .alert("Replace the edited kit?", isPresented: $showReplacementConfirmation) {
            Button("Discard edits and open kit", role: .destructive) { model.confirmReplacement() }
            Button("Keep editing", role: .cancel) { model.cancelReplacement() }
        } message: { Text("Export a copy first if you want to keep these edits. The original file is unchanged.") }
        .alert(model.errorTitle, isPresented: Binding(
            get: { model.errorMessage != nil && editing == nil }, set: { if !$0 { model.errorMessage = nil } })) {
            Button("OK", role: .cancel) { model.errorMessage = nil }
        } message: { Text(model.errorMessage ?? "") }
    }

    @ToolbarContentBuilder
    private var controls: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Button("Done", action: close).frame(minHeight: 44)
                .accessibilityIdentifier("close-inspector").disabled(model.busy)
        }
        ToolbarItemGroup(placement: .topBarTrailing) {
            if model.isLoading || model.isExporting { ProgressView() }
            if model.kit != nil {
                Menu("Edit actions", systemImage: "ellipsis.circle") {
                    Button("Undo", systemImage: "arrow.uturn.backward", action: model.undo)
                        .disabled(model.session?.undoLabel == nil).accessibilityIdentifier("kit-undo")
                    Button("Redo", systemImage: "arrow.uturn.forward", action: model.redo)
                        .disabled(model.session?.redoLabel == nil).accessibilityIdentifier("kit-redo")
                    Button("Export new copy…", systemImage: "square.and.arrow.up") {
                        exportingFolder = true
                        model.chooseExportFolder()
                    }
                        .accessibilityIdentifier("kit-export")
                    Button("Try synthetic kit") { Task { await model.demo() } }
                        .accessibilityIdentifier("kit-reload-demo")
                }.labelStyle(.iconOnly).frame(minWidth: 44, minHeight: 44)
                    .accessibilityIdentifier("kit-actions").disabled(model.busy)
            }
            Button("Open kit", systemImage: "folder", action: chooseFile)
                .labelStyle(.iconOnly).frame(minWidth: 44, minHeight: 44)
                .accessibilityIdentifier("import-kit").disabled(model.busy)
        }
    }

    private var welcome: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Image(systemName: "circle.grid.3x3").font(.system(size: 48)).foregroundStyle(Stage.brass)
                Text("Make the kit yours.").font(.largeTitle.weight(.semibold))
                Text("Open a Strike .skt file to edit its pad settings and Layer A/B assignments, then export a new copy.")
                    .font(.title3)
                Button("Open kit", systemImage: "folder", action: chooseFile)
                    .buttonStyle(.borderedProminent).foregroundStyle(.black).frame(minHeight: 44).disabled(model.busy)
                Button("Try synthetic kit") { Task { await model.demo() } }
                    .frame(minHeight: 44).accessibilityIdentifier("kit-demo").disabled(model.busy)
                Text("Original files stay untouched. Assignments use references already in the kit; sound availability isn’t checked. Export your edits before closing the app.")
                    .font(.footnote).foregroundStyle(.secondary)
            }.padding(28).frame(maxWidth: 560, alignment: .leading).frame(maxWidth: .infinity)
        }
    }

    private func chooseFile() {
        exportingFolder = false
        model.choosingFile = true
    }

    private var status: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(model.isDirty ? "Edited copy" : "Original imported", systemImage: model.isDirty ? "pencil.circle" : "doc")
                .font(.subheadline.weight(.medium)).foregroundStyle(Stage.brass).accessibilityIdentifier("kit-edit-status")
            Text("Edits stay open when you tap Done. Export a copy before closing the app.")
                .font(.footnote).foregroundStyle(.secondary)
            if let message = model.exportMessage {
                Text(message).font(.footnote).foregroundStyle(Stage.brass).accessibilityIdentifier("kit-export-status")
            }
        }
    }

    private func zones(_ kit: KitInspection, wide: Bool) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 12) {
                Text("\(kit.pads.count) pad zones").font(.title2.weight(.semibold))
                status
                if let issue = kit.editingIssue { Text(issue).font(.footnote).foregroundStyle(Stage.brass) }
                if kit.unresolvedCount > 0 {
                    Text("\(kit.unresolvedCount) assignments have unresolved string indices.").font(.footnote).foregroundStyle(Stage.brass)
                }
            }.padding()
            if !typeSize.isAccessibilitySize {
                Picker("Kit view", selection: $showDrumMap) {
                    Text("Zones").tag(false)
                    Text("Drum map").tag(true)
                }.pickerStyle(.segmented).padding(.horizontal).padding(.bottom, 12)
                    .accessibilityIdentifier("kit-workspace-view")
            }
            if usingDrumMap {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        KitDrumMap(kit: kit, selected: model.selected) { selectZone($0, wide: wide) }
                        Text("Standard layout. Swipe across to see the whole kit. All zones remain available in Zones.")
                            .font(.footnote).foregroundStyle(.secondary).padding(.horizontal)
                    }.padding(.bottom)
                }
            } else {
                List(kit.pads.indices, id: \.self) { index in
                    let pad = kit.pads[index]
                    Group {
                        if wide {
                            Button { model.selected = index } label: { zoneLabel(pad) }
                                .accessibilityAddTraits(model.selected == index ? [.isSelected] : [])
                        } else { NavigationLink(value: index) { zoneLabel(pad) } }
                    }.accessibilityIdentifier("kit-zone-\(pad.id)")
                        .listRowBackground(wide && model.selected == index ? Stage.brass.opacity(0.14) : Stage.background)
                }.listStyle(.plain).scrollContentBackground(.hidden)
            }
            if kit.pads.isEmpty { Text("This kit has no pad zones.").padding() }
        }
    }

    private func selectZone(_ index: Int, wide: Bool) {
        model.selected = index
        if !wide { path = [index] }
    }

    @ViewBuilder
    private func zoneChoices(_ kit: KitInspection, index: Int, wide: Bool) -> some View {
        let siblings = KitMapLayout.zoneIndices(in: kit, for: index)
        if siblings.count > 1 {
            ScrollView(.horizontal) {
                HStack(spacing: 8) {
                    ForEach(siblings, id: \.self) { sibling in
                        Button(kit.pads[sibling].label) { selectZone(sibling, wide: wide) }
                            .buttonStyle(.bordered).tint(sibling == index ? Stage.brass : .secondary)
                            .frame(minHeight: 44).accessibilityAddTraits(sibling == index ? [.isSelected] : [])
                            .accessibilityIdentifier("kit-detail-zone-\(kit.pads[sibling].id)")
                    }
                }
            }
        }
    }

    private func zoneLabel(_ pad: KitPad) -> some View {
        HStack(spacing: 12) {
            Text(pad.id).font(.system(.caption, design: .monospaced)).foregroundStyle(Stage.brass).frame(width: 38)
            Text(pad.label).foregroundStyle(.primary)
        }.frame(minHeight: 44, alignment: .leading)
    }

    private func detail(_ kit: KitInspection, index: Int, wide: Bool) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                if kit.pads.indices.contains(index) {
                    let pad = kit.pads[index]
                    Text(pad.label).font(.largeTitle.weight(.semibold)).accessibilityIdentifier("kit-pad-title")
                    Text("\(pad.id) · Edit a copy").font(.subheadline).foregroundStyle(.secondary)
                    if !wide { status }
                    zoneChoices(kit, index: index, wide: wide)
                    if let issue = kit.editingIssue { Text(issue).font(.footnote).foregroundStyle(Stage.brass) }
                    if !pad.isKnownZone { Text("This unknown zone can be inspected but not edited.").foregroundStyle(Stage.brass) }
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 260), spacing: 32, alignment: .topLeading)], alignment: .leading, spacing: 24) {
                        layer(kit, index: index, name: "Layer A", number: 0, reference: pad.layerA)
                        layer(kit, index: index, name: "Layer B", number: 1, reference: pad.layerB)
                    }
                    Divider()
                    Text("Zone settings").font(.title2.weight(.semibold)).foregroundStyle(Stage.brass)
                    ForEach(KitParameter.allCases.filter { $0.layer == nil }) { parameter in
                        parameterRow(parameter, kit: kit, index: index)
                    }
                    Divider()
                    Text("Sound availability not checked. References are text from this kit; no instruments, samples or cards have been opened.")
                        .font(.footnote).foregroundStyle(.secondary)
                } else { Text("Select a pad zone.").font(.title2) }
            }.padding(28).frame(maxWidth: 860, alignment: .leading).frame(maxWidth: .infinity, alignment: .topLeading)
        }.id("\(model.documentID)-\(index)").background(Stage.sheet).accessibilityIdentifier("kit-detail")
    }

    private func layer(_ kit: KitInspection, index: Int, name: String, number: Int, reference: Int) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(name).font(.title2.weight(.semibold)).foregroundStyle(Stage.brass)
            Text(kit.reference(reference)).font(.headline).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier(number == 0 ? "kit-layer-a" : "kit-layer-b")
            Button("Change assignment", systemImage: "arrow.triangle.2.circlepath") {
                editing = KitEditRequest(documentID: model.documentID, pad: index, parameter: nil, layer: number)
            }.frame(minHeight: 44).accessibilityIdentifier("kit-assign-\(number)")
                .disabled(model.busy || kit.editingIssue != nil || !kit.pads[index].isKnownZone)
            ForEach(KitParameter.allCases.filter { $0.layer == number && !$0.rawValue.contains("Velocity") }) { parameter in
                parameterRow(parameter, kit: kit, index: index)
            }
            DisclosureGroup("Velocity response") {
                ForEach(KitParameter.allCases.filter { $0.layer == number && $0.rawValue.contains("Velocity") }) { parameter in
                    parameterRow(parameter, kit: kit, index: index)
                }
                if number == 1 { LabeledContent("Velocity maximum", value: String(kit.pads[index].byte(40))) }
            }.frame(minHeight: 44).padding(.top, 8)
        }.frame(maxWidth: .infinity, alignment: .topLeading)
    }

    private func parameterRow(_ parameter: KitParameter, kit: KitInspection, index: Int) -> some View {
        Button {
            editing = KitEditRequest(documentID: model.documentID, pad: index, parameter: parameter, layer: nil)
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(parameter.title).foregroundStyle(.secondary)
                Spacer(minLength: 8)
                Text(parameter.display(parameter.value(in: kit.pads[index]))).foregroundStyle(.primary).monospacedDigit()
                Image(systemName: "chevron.right").font(.caption2).foregroundStyle(Stage.brass)
            }.frame(minHeight: 44).contentShape(Rectangle())
        }.buttonStyle(.plain).accessibilityIdentifier("kit-edit-\(parameter.rawValue)")
            .disabled(model.busy || kit.editingIssue != nil || !kit.pads[index].isKnownZone)
    }
}
