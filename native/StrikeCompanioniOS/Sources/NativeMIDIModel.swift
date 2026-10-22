import Foundation
import Combine

@MainActor
final class NativeMIDIModel: ObservableObject {
    @Published private(set) var inputs: [NativeMIDIInput] = []
    @Published var selectedInput: Int32?
    @Published private(set) var isRecording = false
    @Published private(set) var take: DrumMIDITake?
    @Published private(set) var status = "Refresh inputs, choose one, then Record."
    @Published private(set) var notes: [DrumMIDINoteSummary] = []
    @Published private(set) var hiHat: [Int: Int] = [:]
    @Published private(set) var recent: [DrumMIDIEvent] = []
    @Published private(set) var learning = false
    @Published private(set) var candidate: DrumMIDIMessage?
    @Published var errorMessage: String?
    private let driver: any NativeMIDIInputDriver
    private let clock: () -> Double
    private let usesTimer: Bool
    private var mailbox: DrumMIDIMailbox?
    private var timer: Timer?
    private var started = 0.0
    private var armed = 0.0
    private var activeInput: Int32?
    private var summaries: [String: DrumMIDINoteSummary] = [:]

    init(driver: (any NativeMIDIInputDriver)? = nil, clock: @escaping () -> Double = { NativeMIDIHostClock.live.now() }, usesTimer: Bool = true) {
        self.driver = driver ?? CoreMIDIInputDriver()
        self.clock = clock
        self.usesTimer = usesTimer
        self.driver.changed = { [weak self] in self?.sourceChanged() }
        self.driver.disconnected = { [weak self] in
            self?.stop(partial: true, reason: "Input disconnected. Partial take retained. Refresh and choose an input to record again.")
            self?.selectedInput = nil
        }
        self.driver.failed = { [weak self] code in
            guard let self, self.isRecording else { return }
            self.stop(partial: true, reason: "Input driver failed. Partial take retained. Refresh and choose an input to record again.")
            self.selectedInput = nil
            self.errorMessage = "MIDI input driver error (\(code)). Your partial take is retained for export."
        }
    }
    static func live() -> NativeMIDIModel {
        #if DEBUG
        let env = ProcessInfo.processInfo.environment
        if env["STRIKE_UI_TEST_MIDI"] == "1", let slot = env["STRIKE_UI_TEST_SESSION"], UUID(uuidString: slot) != nil {
            return NativeMIDIModel(driver: SyntheticMIDIInputDriver())
        }
        #endif
        return NativeMIDIModel()
    }
    func refresh() {
        guard !isRecording else { return }
        do {
            inputs = try driver.inputs()
            if !inputs.contains(where: { $0.id == selectedInput }) { selectedInput = nil }
            status = inputs.isEmpty ? "No MIDI inputs visible. Connect your module, then refresh." : "Choose an input, then Record."
            errorMessage = nil
        } catch { errorMessage = error.localizedDescription }
    }
    private func sourceChanged() {
        guard isRecording, let activeInput else { return }
        do {
            if try !driver.inputs().contains(where: { $0.id == activeInput }) {
                stop(partial: true, reason: "Input disconnected. Partial take retained. Refresh and choose an input to record again.")
                selectedInput = nil
            }
        } catch { stop(partial: true, reason: "Input check failed. Partial take retained."); errorMessage = error.localizedDescription }
    }
    /// A retained take may be replaced only after explicit discard confirmation in the view.
    func record(discardCurrent: Bool = false) {
        guard !isRecording, take == nil || discardCurrent, let selectedInput,
              let input = inputs.first(where: { $0.id == selectedInput }) else { return }
        let box = DrumMIDIMailbox()
        let begin = clock()
        do { try driver.start(selectedInput, mailbox: box) }
        catch {
            driver.stop(); box.close()
            errorMessage = error.localizedDescription
            status = "Input could not be opened. Current take retained. Refresh before trying again."
            return
        }
        started = begin
        activeInput = selectedInput
        mailbox = box
        take = DrumMIDITake(source: input.name, synthetic: driver.synthetic)
        summaries = [:]; notes = []; hiHat = [:]; recent = []
        learning = false; candidate = nil
        errorMessage = nil
        isRecording = true
        status = "Recording input only. No sound or MIDI output."
        if usesTimer {
            timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
                Task { @MainActor [weak self] in self?.poll() }
            }
        }
    }
    func poll() {
        guard isRecording else { return }
        let failure = consume()
        if failure { stop(partial: true, reason: "Input exceeded supported data or queue limits. Partial take retained.") }
        else if take?.events.count == DrumMIDITake.maximumEvents {
            stop(partial: true, reason: "50,000-message limit reached. Partial take retained.")
        }
        else if (clock() - started) * 1000 >= DrumMIDITake.maximumDuration {
            stop(partial: true, reason: "20-minute limit reached. Partial take retained.")
        }
    }
    /// Returns true if any channel data could not be retained.
    private func consume() -> Bool {
        guard let mailbox, var current = take else { return false }
        let batch = mailbox.drain()
        var failed = batch.failed
        for entry in batch.entries {
            let milliseconds = max(0, (entry.uptime - started) * 1000)
            guard current.append(entry.message, milliseconds: milliseconds) else { failed = true; break }
            let message = entry.message
            if message.isHit {
                let key = "\(message.channel):\(message.data[1])"
                var summary = summaries[key] ?? DrumMIDINoteSummary(channel: message.channel, note: Int(message.data[1]))
                let velocity = Int(message.data[2])
                summary.hits += 1; summary.total += velocity
                summary.minimum = min(summary.minimum, velocity); summary.maximum = max(summary.maximum, velocity)
                summaries[key] = summary
                if learning, candidate == nil, entry.uptime >= armed { candidate = message }
            }
            if message.kind == 11 && message.data[1] == 4 { hiHat[message.channel] = Int(message.data[2]) }
            recent.append(current.events.last!)
            if recent.count > 12 { recent.removeFirst(recent.count - 12) }
        }
        current.finish(milliseconds: (clock() - started) * 1000, partial: false)
        take = current
        notes = summaries.values.sorted { ($0.channel, $0.note) < ($1.channel, $1.note) }
        return failed
    }
    func stop(partial: Bool = false, reason: String = "Stopped. Take retained for export.") {
        guard isRecording else { return } // Later disconnects cannot downgrade a completed take.
        driver.stop()
        timer?.invalidate(); timer = nil
        let failed = consume()
        take?.finish(milliseconds: (clock() - started) * 1000, partial: partial || failed)
        isRecording = false; activeInput = nil
        mailbox = nil; learning = false; candidate = nil
        // The mailbox keeps its failure flag, so a partial stop must keep its specific reason.
        status = failed && !partial ? "Input limit reached. Partial take retained for export." : reason
    }
    func leave() { stop(); driver.close() }
    func background() {
        stop(partial: true, reason: "Recording stopped when the app left the foreground. Partial take retained; reconnect explicitly.")
        driver.close()
    }
    func armLearn() {
        guard isRecording else { return }
        // Exclude hits already queued before the user asked to Learn.
        poll()
        guard isRecording else { return }
        armed = clock(); learning = true; candidate = nil
    }
    func cancelLearn() { learning = false; candidate = nil }
    func applyName(_ label: String) {
        guard isRecording, learning, let candidate else { return }
        guard take?.namePad(channel: candidate.channel, note: Int(candidate.data[1]), label: label) == true else {
            errorMessage = "Use a name of 1–80 characters on one line. A take can name at most 128 channel/note pairs."
            return
        }
        cancelLearn()
    }
    func exported() throws -> Data {
        guard !isRecording, let take else { throw CocoaError(.fileReadUnknown) }
        return try take.exported()
    }
}
