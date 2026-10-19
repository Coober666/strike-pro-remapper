import SwiftUI
import StrikeSetlists

struct KitEditRequest: Identifiable {
    let documentID: UUID
    let pad: Int
    let parameter: KitParameter?
    let layer: Int?
    var id: String { "\(documentID)-\(pad)-\(parameter?.rawValue ?? "assignment\(layer ?? 0)")" }
}

struct KitEditSheet: View {
    let request: KitEditRequest
    let kit: KitInspection
    let apply: (Int) -> Bool
    @State private var input: String
    @State private var reference: Int
    @State private var query = ""
    @FocusState private var valueFocused: Bool
    @Environment(\.dismiss) private var dismiss

    init(request: KitEditRequest, kit: KitInspection, apply: @escaping (Int) -> Bool) {
        self.request = request; self.kit = kit; self.apply = apply
        let pad = kit.pads[request.pad]
        _input = State(initialValue: String(request.parameter?.value(in: pad) ?? 0))
        _reference = State(initialValue: request.layer == 0 ? pad.layerA : pad.layerB)
    }
    private var value: Int? { Int(input) }
    private var valid: Bool {
        if let parameter = request.parameter {
            guard let value, parameter.accepts(value) else { return false }
            let pad = kit.pads[request.pad]
            if parameter == .aVelocityMinimum { return value <= pad.byte(20) }
            if parameter == .aVelocityMaximum { return value >= pad.byte(19) }
            if parameter == .bVelocityMinimum { return value <= pad.byte(40) }
            return true
        }
        return reference == 65535 || kit.instruments.indices.contains(reference)
    }
    var body: some View {
        NavigationStack {
            Group {
                if let parameter = request.parameter { valueForm(parameter) }
                else { assignments }
            }
            .navigationTitle(request.parameter?.title ?? "Layer \(request.layer == 0 ? "A" : "B") assignment")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { valueFocused = false; dismiss() }.frame(minHeight: 44).accessibilityIdentifier("kit-edit-cancel")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Apply") {
                        guard valid, let candidate = request.parameter == nil ? reference : value else { return }
                        valueFocused = false
                        if apply(candidate) { dismiss() }
                    }.frame(minHeight: 44).disabled(!valid).accessibilityIdentifier("kit-edit-apply")
                }
            }
        }.tint(Stage.brass).preferredColorScheme(.dark)
    }
    private func valueForm(_ parameter: KitParameter) -> some View {
        Form {
            Section {
                Text(kit.pads[request.pad].label).foregroundStyle(Stage.brass)
                if let layer = parameter.layer { Text("Layer \(layer == 0 ? "A" : "B")") }
            }
            Section {
                if let options = parameter.options {
                    Picker(parameter.title, selection: $input) {
                        if !valid { Text("Unknown (\(input))").tag(input) }
                        ForEach(options.indices, id: \.self) { Text(options[$0]).tag(String($0)) }
                    }.pickerStyle(.inline)
                } else if parameter == .gateTime {
                    Picker("Gate time", selection: $input) {
                        if !valid { Text("Unknown (\(input))").tag(input) }
                        ForEach(Array(0...109) + [255], id: \.self) { Text(parameter.display($0)).tag(String($0)) }
                    }
                } else {
                    TextField(parameter.title, text: $input).keyboardType(.numbersAndPunctuation).focused($valueFocused)
                        .accessibilityIdentifier("kit-edit-value")
                    Stepper("Adjust value", value: Binding(get: { value ?? parameter.range.lowerBound },
                        set: { input = String($0) }), in: parameter.range).frame(minHeight: 44)
                    Text("\(parameter.range.lowerBound) to \(parameter.range.upperBound)").foregroundStyle(.secondary)
                    if parameter == .aVelocityMinimum || parameter == .aVelocityMaximum || parameter == .bVelocityMinimum {
                        Text("Velocity minimum must not exceed maximum.").font(.footnote).foregroundStyle(.secondary)
                    }
                }
                if !valid { Text("Enter a supported value before applying.").foregroundStyle(Stage.brass) }
            } footer: { Text("Apply changes this open copy. Export a new copy to keep your edits.") }
        }.scrollContentBackground(.hidden).background(Stage.sheet)
    }
    private var assignments: some View {
        List {
            Section {
                Text("Choose a reference already stored in this kit. Sound availability isn’t checked.").font(.footnote)
                assignmentRow("Unassigned", index: 65535)
            }
            Section("Kit references") {
                ForEach(kit.instruments.indices.filter { query.isEmpty || kit.instruments[$0].localizedCaseInsensitiveContains(query) }, id: \.self) { index in
                    assignmentRow(kit.instruments[index], index: index)
                }
            }
        }.searchable(text: $query, prompt: "Search kit references").scrollContentBackground(.hidden).background(Stage.sheet)
    }
    private func assignmentRow(_ title: String, index: Int) -> some View {
        Button { reference = index } label: {
            HStack {
                Text(title).foregroundStyle(.primary).fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 12)
                if reference == index { Image(systemName: "checkmark").foregroundStyle(Stage.brass) }
            }.frame(minHeight: 44)
        }.accessibilityIdentifier("kit-reference-\(index)").accessibilityAddTraits(reference == index ? [.isSelected] : [])
    }
}
