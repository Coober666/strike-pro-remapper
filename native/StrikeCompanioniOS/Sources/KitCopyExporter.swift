import Foundation
import Darwin
import StrikeSetlists

/// The only kit write path. A user-selected folder receives an exclusively created new file.
enum KitCopyExporter {
    static func copy(_ data: Data, to directory: URL) throws -> URL {
        let access = directory.startAccessingSecurityScopedResource()
        defer { if access { directory.stopAccessingSecurityScopedResource() } }
        var coordinationError: NSError?
        var outcome: Result<URL, Error>?
        NSFileCoordinator().coordinate(writingItemAt: directory, options: [],
                                       error: &coordinationError) { coordinatedDirectory in
            outcome = Result { try create(data, in: coordinatedDirectory) }
        }
        if let coordinationError { throw coordinationError }
        guard let outcome else { throw SetlistError.invalid("Files did not provide an export destination.") }
        return try outcome.get()
    }

    // Internal seam permits collision and partial-write fault tests in disposable directories.
    static func create(_ data: Data, in directory: URL,
                       name: String = "Kit-edit-" + UUID().uuidString.prefix(8).lowercased() + ".skt",
                       write: (FileHandle, Data) throws -> Void = { try $0.write(contentsOf: $1) }) throws -> URL {
        guard directory.isFileURL,
              name.range(of: #"\AKit-edit-[0-9a-f]{8}\.skt\z"#, options: .regularExpression) != nil else {
            throw SetlistError.invalid("Choose a folder for a new kit copy.")
        }
        let checked = try KitInspection.decode(data)
        guard checked.encoded() == data else { throw SetlistError.invalid("The edited kit failed its round-trip check.") }
        let folder = directory.withUnsafeFileSystemRepresentation { Darwin.open($0!, O_RDONLY | O_DIRECTORY | O_NOFOLLOW) }
        guard folder >= 0 else { throw posixError() }
        defer { Darwin.close(folder) }
        let descriptor = name.withCString { openat(folder, $0, O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600) }
        guard descriptor >= 0 else { throw posixError() } // Never open/truncate an existing item, even a symbolic link.
        let file = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        var identity = stat()
        guard fstat(descriptor, &identity) == 0 else {
            let error = posixError()
            try? file.close()
            throw SetlistError.invalid("Couldn’t inspect the new copy \(name). Check the destination before retrying. \(error.localizedDescription)")
        }
        do {
            try write(file, data)
            try file.synchronize()
            try file.seek(toOffset: 0)
            let written = try file.read(upToCount: KitInspection.maximumBytes + 1) ?? Data()
            guard written == data, try KitInspection.decode(written).encoded() == data else {
                throw SetlistError.invalid("The exported copy could not be verified.")
            }
            var published = stat()
            guard name.withCString({ fstatat(folder, $0, &published, AT_SYMLINK_NOFOLLOW) == 0 }),
                  published.st_dev == identity.st_dev, published.st_ino == identity.st_ino else {
                throw SetlistError.invalid("The destination changed during export. Check the new copy before retrying.")
            }
            try file.close()
            return directory.appendingPathComponent(name)
        } catch {
            try? file.close()
            // Remove only our own incomplete file. A replacement by another process is never removed.
            var now = stat()
            let same = name.withCString { fstatat(folder, $0, &now, AT_SYMLINK_NOFOLLOW) == 0 } &&
                now.st_dev == identity.st_dev && now.st_ino == identity.st_ino
            if same, name.withCString({ unlinkat(folder, $0, 0) }) != 0 {
                throw SetlistError.invalid("Export stopped and the incomplete copy \(name) could not be removed. \(error.localizedDescription)")
            }
            throw error
        }
    }

    private static func posixError() -> NSError { NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
}
