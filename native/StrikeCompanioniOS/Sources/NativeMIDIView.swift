import SwiftUI
import UniformTypeIdentifiers

struct MIDICaptureDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.json] }
    var data: Data
    init(data: Data) { self.data = data }
    init(configuration: ReadConfiguration) throws {
        throw CocoaError(.fileReadUnsupportedScheme) // Export only; imports retain existing app routing.
    }
    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper { FileWrapper(regularFileWithContents: data) }
}

struct NativeMIDIView: View {
    @ObservedObject var model: NativeMIDIModel
    let done: () -> Void
    @Environment(\.scenePhase) private var scenePhase
    @State private var confirmingRecord = false
    @State private var padName = ""
    @FocusState private var naming: Bool
    @State private var document: MIDICaptureDocument?
    @State private var exporting = false
    @State private var exportStatus: String?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text(model.status).accessibilityIdentifier("midi-status")
                    if model.take?.synthetic == true { Text("Synthetic demo input").foregroundStyle(Stage.brass) }
                    Button("Refresh inputs", action: model.refresh).disabled(model.isRecording || exporting)
                        .frame(minHeight: 44).accessibilityIdentifier("midi-refresh")
                    Picker("Input", selection: $model.selectedInput) {
                        Text("Choose an input").tag(Int32?.none)
                        ForEach(model.inputs) { input in Text(input.name).tag(Optional(input.id)) }
                    }.disabled(model.isRecording || exporting).accessibilityIdentifier("midi-input")
                    HStack {
                        Button {
                            if model.take == nil { model.record() } else { confirmingRecord = true }
                            exportStatus = nil
                        } label: {
                            Text(model.isRecording ? "Recording" : (model.take == nil ? "Record" : "New recording"))
                                .frame(minWidth: 44, minHeight: 44)
                        }.buttonStyle(.borderless).disabled(model.isRecording || model.selectedInput == nil || exporting)
                            .accessibilityIdentifier("midi-record")
                        Spacer()
                        Button { naming = false; model.stop() } label: {
                            Text("Stop").frame(minWidth: 44, minHeight: 44)
                        }.buttonStyle(.borderless).disabled(!model.isRecording)
                            .accessibilityIdentifier("midi-stop")
                    }.frame(minHeight: 44)
                    if let take = model.take {
                        Text("\(take.events.count) messages · \(take.durationMs / 1000, specifier: "%.1f") seconds · \(model.isRecording ? "recording" : take.captureStatus)")
                            .monospacedDigit().accessibilityIdentifier("midi-count")
                        Button("Export capture JSON") {
                            do { document = MIDICaptureDocument(data: try model.exported()); exporting = true; exportStatus = nil }
                            catch { model.errorMessage = error.localizedDescription }
                        }.disabled(model.isRecording || exporting).frame(minHeight: 44).accessibilityIdentifier("midi-export")
                    }
                    if let exportStatus { Text(exportStatus).font(.footnote) }
                } header: { Text("MIDI input") } footer: {
                    Text("Input only and silent. Records MIDI 1 channel messages, up to 50,000 messages or 20 minutes. Recording stops if the app leaves the foreground. Export before closing the app; takes stay in memory.")
                }
                Section("Pad Learn") {
                    Text("Name a received channel/note pair for this take. Kit settings stay as they are.")
                        .font(.subheadline).foregroundStyle(.secondary)
                    if !model.learning {
                        Button("Learn next hit") { padName = ""; model.armLearn() }.disabled(!model.isRecording)
                            .frame(minHeight: 44).accessibilityIdentifier("midi-learn")
                    } else {
                        if let candidate = model.candidate {
                            Text("Channel \(candidate.channel), note \(candidate.data[1]), velocity \(candidate.data[2])")
                                .accessibilityIdentifier("midi-candidate")
                            if let existing = model.take?.padMap.mappings.first(where: {
                                $0.channel == candidate.channel && $0.note == Int(candidate.data[1])
                            }) { Text("Current name: \(existing.label)").font(.footnote) }
                            TextField("Pad name", text: $padName).focused($naming).submitLabel(.done)
                                .textFieldStyle(.roundedBorder).frame(minHeight: 44)
                                .contentShape(Rectangle())
                                .simultaneousGesture(TapGesture().onEnded { naming = true })
                                .onSubmit { naming = false }.accessibilityIdentifier("midi-pad-name")
                            Button("Apply name") { naming = false; model.applyName(padName); if !model.learning { padName = "" } }
                                .disabled(trimmedMIDIText(padName).isEmpty)
                                .frame(minHeight: 44).accessibilityIdentifier("midi-apply-name")
                        } else { Text("Play one pad now, then confirm its name.").accessibilityIdentifier("midi-waiting") }
                        Button("Cancel Learn") { naming = false; padName = ""; model.cancelLearn() }.frame(minHeight: 44)
                    }
                    ForEach(model.take?.padMap.mappings ?? [], id: \.selfID) { mapping in
                        Text("Ch \(mapping.channel) / \(mapping.note): \(mapping.label)")
                    }
                }
                Section("Notes and velocity") {
                    if model.notes.isEmpty { Text("Received positive Note Ons appear here.").foregroundStyle(.secondary) }
                    ForEach(model.notes) { note in
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Ch \(note.channel) / Note \(note.note)").font(.headline)
                            Text("\(note.hits) hits · velocity \(note.minimum)–\(note.maximum) · mean \(note.mean, specifier: "%.1f")")
                                .monospacedDigit().font(.subheadline)
                        }.padding(.vertical, 4).accessibilityElement(children: .combine)
                            .accessibilityIdentifier("midi-note-\(note.id)")
                    }
                }
                Section("Hi-hat controller") {
                    if model.hiHat.isEmpty { Text("CC4 values appear by channel. Open/closed direction depends on the module.").foregroundStyle(.secondary) }
                    ForEach(model.hiHat.keys.sorted(), id: \.self) { channel in
                        Text("Ch \(channel) / CC4: \(model.hiHat[channel] ?? 0)").accessibilityIdentifier("midi-cc4-\(channel)")
                    }
                }
                Section("Recent messages") {
                    ForEach(Array(model.recent.enumerated().reversed()), id: \.offset) { _, event in
                        if let message = DrumMIDIMessage(event.data) {
                            Text("\(message.label) · Ch \(message.channel) · \(event.data.dropFirst().map(String.init).joined(separator: ", "))")
                                .font(.subheadline)
                        }
                    }
                    Text("Velocity is MIDI data, not measured loudness. MIDI alone cannot prove missed hits or trigger faults. Timing is not calibrated.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .scrollContentBackground(.hidden).background(Stage.background)
            .navigationTitle("MIDI tools").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) {
                Button("Done") { model.leave(); done() }.frame(minHeight: 44).accessibilityIdentifier("midi-done")
            } }
        }
        .tint(Stage.brass).preferredColorScheme(.dark)
        .alert("Discard the current take and start a new recording?", isPresented: $confirmingRecord) {
            Button("Discard take and record", role: .destructive) { model.record(discardCurrent: true) }
            Button("Keep take", role: .cancel) { }
        }
        .alert("MIDI tools", isPresented: Binding(get: { model.errorMessage != nil }, set: { if !$0 { model.errorMessage = nil } })) {
            Button("OK", role: .cancel) { model.errorMessage = nil }
        } message: { Text(model.errorMessage ?? "") }
        .fileExporter(isPresented: $exporting, document: document, contentType: .json,
                      defaultFilename: "Drum-MIDI-\(UUID().uuidString.prefix(8))") { result in
            switch result {
            case .success: exportStatus = "Capture exported. Reopen the JSON in the web MIDI toolkit to analyze it further."
            case .failure(let error):
                if (error as NSError).code != NSUserCancelledError {
                    model.errorMessage = "Export could not be confirmed. Your take is still open. Check the destination before trying again."
                }
            }
        }
        .onChange(of: scenePhase) { _, phase in if phase != .active { model.background() } }
        .onDisappear { model.leave() }
    }
}

private extension DrumMIDIPadName { var selfID: String { "\(channel):\(note)" } }
