import SwiftUI
import StrikeSetlists

/// Selection topology only. Unknown zones stay independent in the complete Zones list.
enum KitMapLayout {
    struct Position: Identifiable {
        let id: String
        let name: String
        let x: CGFloat
        let y: CGFloat
        let cymbal: Bool
    }
    static let positions: [Position] = [
        .init(id: "C1", name: "Crash 1", x: 0.14, y: 0.14, cymbal: true),
        .init(id: "C2", name: "Crash 2", x: 0.44, y: 0.10, cymbal: true),
        .init(id: "C3", name: "Crash 3", x: 0.70, y: 0.14, cymbal: true),
        .init(id: "R1", name: "Ride", x: 0.87, y: 0.34, cymbal: true),
        .init(id: "H1", name: "Hi-hat", x: 0.13, y: 0.47, cymbal: true),
        .init(id: "T1", name: "Tom 1", x: 0.33, y: 0.36, cymbal: false),
        .init(id: "T2", name: "Tom 2", x: 0.54, y: 0.35, cymbal: false),
        .init(id: "T3", name: "Tom 3", x: 0.75, y: 0.53, cymbal: false),
        .init(id: "S1", name: "Snare", x: 0.31, y: 0.64, cymbal: false),
        .init(id: "T4", name: "Tom 4", x: 0.88, y: 0.79, cymbal: false),
        .init(id: "K1", name: "Kick 1", x: 0.54, y: 0.78, cymbal: false),
        .init(id: "K2", name: "Kick 2", x: 0.28, y: 0.88, cymbal: false)
    ]

    static func primaryIndex(in kit: KitInspection, group: String) -> Int? {
        // Prefer head/bow regardless of chunk order; an isolated rim/edge/bell is still reachable.
        let preferred = group + (["R1", "H1"].contains(group) || group.hasPrefix("C") ? "B" : "H")
        return kit.pads.firstIndex { $0.id == preferred } ?? kit.pads.firstIndex {
            $0.isKnownZone && String($0.id.prefix(2)) == group
        }
    }

    static func zoneIndices(in kit: KitInspection, for index: Int) -> [Int] {
        guard kit.pads.indices.contains(index) else { return [] }
        guard kit.pads[index].isKnownZone else { return [index] }
        return kit.pads.indices.filter {
            kit.pads[$0].isKnownZone && kit.pads[$0].id.prefix(2) == kit.pads[index].id.prefix(2)
        }
    }
}

/// A standard arrangement of the zones actually present in the open kit.
/// This view changes selection only; it never auditions or mutates kit bytes.
struct KitDrumMap: View {
    let kit: KitInspection
    let selected: Int
    let select: (Int) -> Void

    var body: some View {
        GeometryReader { geometry in
            let width = max(560, geometry.size.width)
            ScrollView(.horizontal) {
                ZStack {
                    Ellipse().stroke(.white.opacity(0.05), lineWidth: 1)
                        .frame(width: width * 0.70, height: 330).position(x: width * 0.50, y: 235)
                    ForEach(KitMapLayout.positions) { position in
                        if let index = KitMapLayout.primaryIndex(in: kit, group: position.id) {
                            pad(position, index: index)
                                .position(x: width * position.x, y: 430 * position.y)
                        }
                    }
                }.frame(width: width, height: 430)
            }.accessibilityIdentifier("kit-drum-map")
        }.frame(height: 446)
    }

    private func pad(_ position: KitMapLayout.Position, index: Int) -> some View {
        let active = KitMapLayout.zoneIndices(in: kit, for: index).contains(selected)
        let metal = Color(red: 0.57, green: 0.48, blue: 0.31)
        return Button { select(index) } label: {
            VStack(spacing: 6) {
                ZStack {
                    Circle().fill(position.cymbal ? metal.opacity(0.72) : Color(red: 0.37, green: 0.20, blue: 0.19))
                    Circle().fill(position.cymbal ? Stage.brass.opacity(0.20) : Stage.sheet)
                        .padding(position.cymbal ? 5 : 7)
                    Circle().stroke(.white.opacity(position.cymbal ? 0.20 : 0.35), lineWidth: 1).padding(5)
                    Circle().stroke(.white.opacity(0.09), lineWidth: 1).padding(13)
                    if position.cymbal {
                        Circle().fill(metal).frame(width: 20, height: 20)
                        Circle().fill(.black.opacity(0.45)).frame(width: 4, height: 4)
                    } else {
                        ForEach(0..<6, id: \.self) { lug in
                            Capsule().fill(.white.opacity(0.55)).frame(width: 4, height: 7)
                                .offset(y: -30).rotationEffect(.degrees(Double(lug) * 60))
                        }
                    }
                    Circle().stroke(active ? Stage.brass : .clear, lineWidth: 3).padding(1)
                }.frame(width: 72, height: 72)
                Text(position.name).font(.subheadline.weight(active ? .semibold : .regular))
                    .foregroundStyle(active ? Stage.brass : .primary).fixedSize()
            }.padding(4).contentShape(Rectangle())
        }.buttonStyle(.plain)
            .accessibilityLabel(kit.pads[index].label)
            .accessibilityValue(active ? "Selected pad" : "")
            .accessibilityAddTraits(active ? [.isSelected] : [])
            .accessibilityIdentifier("kit-zone-\(kit.pads[index].id)")
    }
}
