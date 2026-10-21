#import <Cocoa/Cocoa.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#include <math.h>

@protocol RecordingDropHandling <NSObject>
- (BOOL)canAcceptRecordingDrop:(id<NSDraggingInfo>)sender;
- (BOOL)acceptRecordingDrop:(id<NSDraggingInfo>)sender;
@end

@interface RecordingDropBox : NSBox
@property (weak) id<RecordingDropHandling> dropHandler;
@end

@implementation RecordingDropBox

- (instancetype)init {
    self = [super init];
    if (self) [self registerForDraggedTypes:@[NSPasteboardTypeFileURL]];
    return self;
}

- (void)setDropHighlighted:(BOOL)highlighted {
    self.borderColor = highlighted ? NSColor.systemBlueColor : NSColor.separatorColor;
    self.borderWidth = highlighted ? 2.0 : 1.0;
}

- (NSDragOperation)draggingEntered:(id<NSDraggingInfo>)sender {
    BOOL accepted = [self.dropHandler canAcceptRecordingDrop:sender];
    [self setDropHighlighted:accepted];
    return accepted ? NSDragOperationCopy : NSDragOperationNone;
}

- (NSDragOperation)draggingUpdated:(id<NSDraggingInfo>)sender {
    return [self.dropHandler canAcceptRecordingDrop:sender] ? NSDragOperationCopy : NSDragOperationNone;
}

- (void)draggingExited:(id<NSDraggingInfo>)sender { [self setDropHighlighted:NO]; }

- (BOOL)performDragOperation:(id<NSDraggingInfo>)sender {
    [self setDropHighlighted:NO];
    return [self.dropHandler acceptRecordingDrop:sender];
}

- (void)concludeDragOperation:(id<NSDraggingInfo>)sender { [self setDropHighlighted:NO]; }

@end

@interface AppDelegate : NSObject <NSApplicationDelegate, RecordingDropHandling>
@property NSWindow *window;
@property RecordingDropBox *recordingBox;
@property NSTextField *fileLabel;
@property NSTextField *filePathLabel;
@property NSButton *chooseButton;
@property NSPopUpButton *languagePopup;
@property NSButton *speakerCheckbox;
@property NSTextField *outputLabel;
@property NSButton *outputButton;
@property NSButton *startButton;
@property NSButton *showButton;
@property NSTextField *statusLabel;
@property NSTextField *fileProgressLabel;
@property NSTextField *overallProgressLabel;
@property NSTextField *timingLabel;
@property NSProgressIndicator *fileProgress;
@property NSProgressIndicator *overallProgress;
@property NSTextView *logView;
@property NSScrollView *logScroll;
@property NSTextField *logLabel;
@property NSButton *logToggleButton;
@property NSLayoutConstraint *logHeightConstraint;
@property NSArray<NSURL *> *sourceURLs;
@property NSArray<NSURL *> *batchURLs;
@property NSMutableArray<NSNumber *> *batchDurations;
@property NSMutableArray<NSNumber *> *batchEstimates;
@property NSMutableArray<NSURL *> *resultURLs;
@property NSMutableArray<NSURL *> *readableResultURLs;
@property NSUInteger batchIndex;
@property NSUInteger succeededCount;
@property NSUInteger failedCount;
@property NSURL *outputURL;
@property NSURL *resultURL;
@property NSURL *readableResultsURL;
@property NSTask *task;
@property NSMutableString *stdoutBuffer;
@property NSTimer *progressTimer;
@property NSDate *batchStartedAt;
@property NSDate *fileStartedAt;
@property NSDate *stageStartedAt;
@property NSString *currentStage;
@property double currentStageStartFraction;
@property double currentStageEndFraction;
@property BOOL currentFileDidWork;
@end

@implementation AppDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    self.outputURL = [NSURL fileURLWithPath:[NSHomeDirectory() stringByAppendingPathComponent:@"Documents/Local Transcriber"]];
    self.stdoutBuffer = [NSMutableString string];
    [self buildMenu];
    [self buildWindow];
    [NSApp activateIgnoringOtherApps:YES];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender { return YES; }

- (void)buildMenu {
    NSMenu *menuBar = [[NSMenu alloc] init];
    NSMenuItem *appItem = [[NSMenuItem alloc] init];
    [menuBar addItem:appItem];
    NSMenu *appMenu = [[NSMenu alloc] init];
    [appMenu addItemWithTitle:@"Quit Local Transcriber" action:@selector(terminate:) keyEquivalent:@"q"];
    appItem.submenu = appMenu;
    NSApp.mainMenu = menuBar;
}

- (NSTextField *)label:(NSString *)text size:(CGFloat)size weight:(NSFontWeight)weight {
    NSTextField *label = [NSTextField labelWithString:text];
    label.font = [NSFont systemFontOfSize:size weight:weight];
    label.translatesAutoresizingMaskIntoConstraints = NO;
    return label;
}

- (NSButton *)button:(NSString *)title action:(SEL)action {
    NSButton *button = [NSButton buttonWithTitle:title target:self action:action];
    button.translatesAutoresizingMaskIntoConstraints = NO;
    return button;
}

- (NSString *)backendPythonPath {
    NSArray<NSString *> *candidates = @[
        @"/opt/homebrew/opt/python@3.13/bin/python3.13",
        @"/opt/homebrew/bin/python3",
        @"/usr/local/bin/python3",
        @"/usr/bin/python3"
    ];
    for (NSString *path in candidates) {
        if ([NSFileManager.defaultManager isExecutableFileAtPath:path]) return path;
    }
    return nil;
}

- (void)buildWindow {
    self.window = [[NSWindow alloc]
        initWithContentRect:NSMakeRect(0, 0, 760, 730)
        styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
        backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"Local Transcriber";
    self.window.minSize = NSMakeSize(720, 680);
    [self.window center];

    NSView *content = self.window.contentView;
    NSImageView *logo = [[NSImageView alloc] init];
    logo.image = NSApp.applicationIconImage;
    logo.imageScaling = NSImageScaleProportionallyUpOrDown;
    logo.translatesAutoresizingMaskIntoConstraints = NO;
    NSTextField *title = [self label:@"Local Transcriber" size:30 weight:NSFontWeightBold];
    NSTextField *subtitle = [self label:@"Private, on-device English and Québec French transcription" size:14 weight:NSFontWeightRegular];
    subtitle.textColor = NSColor.secondaryLabelColor;

    self.recordingBox = [[RecordingDropBox alloc] init];
    self.recordingBox.title = @"Recording";
    self.recordingBox.boxType = NSBoxCustom;
    self.recordingBox.borderColor = NSColor.separatorColor;
    self.recordingBox.borderWidth = 1;
    self.recordingBox.cornerRadius = 12;
    self.recordingBox.fillColor = NSColor.controlBackgroundColor;
    self.recordingBox.dropHandler = self;
    self.recordingBox.translatesAutoresizingMaskIntoConstraints = NO;
    self.fileLabel = [self label:@"Drop audio or video files here" size:14 weight:NSFontWeightMedium];
    self.filePathLabel = [self label:@"or click Choose Files…" size:11 weight:NSFontWeightRegular];
    self.filePathLabel.textColor = NSColor.secondaryLabelColor;
    self.filePathLabel.lineBreakMode = NSLineBreakByTruncatingMiddle;
    self.chooseButton = [self button:@"Choose Files…" action:@selector(chooseRecording:)];
    [self.recordingBox addSubview:self.fileLabel];
    [self.recordingBox addSubview:self.filePathLabel];
    [self.recordingBox addSubview:self.chooseButton];

    NSTextField *languageLabel = [self label:@"Language" size:13 weight:NSFontWeightMedium];
    self.languagePopup = [[NSPopUpButton alloc] init];
    [self.languagePopup addItemsWithTitles:@[@"Auto-detect English or French", @"English", @"French (Québec)"]];
    self.languagePopup.translatesAutoresizingMaskIntoConstraints = NO;

    NSTextField *speakerLabel = [self label:@"Speakers" size:13 weight:NSFontWeightMedium];
    self.speakerCheckbox = [NSButton checkboxWithTitle:@"Separate different speakers (optional setup)" target:nil action:nil];
    NSString *diarizationPython = [NSHomeDirectory() stringByAppendingPathComponent:
        @"Library/Application Support/Local Transcriber/pyannote-env/bin/python"];
    self.speakerCheckbox.state = [[NSFileManager defaultManager] isExecutableFileAtPath:diarizationPython]
        ? NSControlStateValueOn : NSControlStateValueOff;
    self.speakerCheckbox.translatesAutoresizingMaskIntoConstraints = NO;

    NSTextField *saveLabel = [self label:@"Save to" size:13 weight:NSFontWeightMedium];
    self.outputLabel = [self label:self.outputURL.path size:11 weight:NSFontWeightRegular];
    self.outputLabel.lineBreakMode = NSLineBreakByTruncatingMiddle;
    self.outputButton = [self button:@"Change…" action:@selector(chooseOutput:)];

    self.startButton = [self button:@"Transcribe" action:@selector(startTranscription:)];
    self.startButton.bezelStyle = NSBezelStyleRounded;
    self.startButton.keyEquivalent = @"\r";
    self.startButton.enabled = NO;
    self.showButton = [self button:@"Show Results" action:@selector(showResults:)];
    self.showButton.hidden = YES;
    self.statusLabel = [self label:@"Choose an audio or video recording to begin." size:13 weight:NSFontWeightRegular];
    self.statusLabel.textColor = NSColor.secondaryLabelColor;

    self.fileProgressLabel = [self label:@"Current recording • Waiting to start" size:12 weight:NSFontWeightMedium];
    self.fileProgress = [[NSProgressIndicator alloc] init];
    self.fileProgress.indeterminate = NO;
    self.fileProgress.minValue = 0;
    self.fileProgress.maxValue = 100;
    self.fileProgress.translatesAutoresizingMaskIntoConstraints = NO;
    self.overallProgressLabel = [self label:@"Overall progress • 0%" size:12 weight:NSFontWeightMedium];
    self.overallProgress = [[NSProgressIndicator alloc] init];
    self.overallProgress.indeterminate = NO;
    self.overallProgress.minValue = 0;
    self.overallProgress.maxValue = 100;
    self.overallProgress.translatesAutoresizingMaskIntoConstraints = NO;
    self.timingLabel = [self label:@"Estimated time will appear after transcription starts." size:12 weight:NSFontWeightRegular];
    self.timingLabel.textColor = NSColor.secondaryLabelColor;

    self.logScroll = [[NSScrollView alloc] init];
    self.logScroll.hasVerticalScroller = YES;
    self.logScroll.borderType = NSBezelBorder;
    self.logScroll.translatesAutoresizingMaskIntoConstraints = NO;
    self.logView = [[NSTextView alloc] init];
    self.logView.editable = NO;
    self.logView.selectable = YES;
    self.logView.font = [NSFont monospacedSystemFontOfSize:11 weight:NSFontWeightRegular];
    self.logView.textColor = NSColor.whiteColor;
    self.logView.backgroundColor = [NSColor colorWithWhite:0.07 alpha:1.0];
    self.logView.drawsBackground = YES;
    self.logScroll.documentView = self.logView;
    self.logLabel = [self label:@"Technical log" size:12 weight:NSFontWeightMedium];
    self.logToggleButton = [self button:@"Hide Logs" action:@selector(toggleLogs:)];
    self.logToggleButton.bezelStyle = NSBezelStyleInline;

    NSTextField *privacy = [self label:@"Audio stays on this Mac. Speaker labels are anonymous predictions such as SPEAKER_00." size:11 weight:NSFontWeightRegular];
    privacy.textColor = NSColor.secondaryLabelColor;

    NSArray *views = @[logo, title, subtitle, self.recordingBox, languageLabel, self.languagePopup,
        speakerLabel, self.speakerCheckbox, saveLabel, self.outputLabel, self.outputButton,
        self.startButton, self.statusLabel, self.showButton,
        self.fileProgressLabel, self.fileProgress, self.overallProgressLabel, self.overallProgress, self.timingLabel,
        self.logLabel, self.logToggleButton, self.logScroll, privacy];
    for (NSView *view in views) [content addSubview:view];

    [NSLayoutConstraint activateConstraints:@[
        [logo.topAnchor constraintEqualToAnchor:content.topAnchor constant:20],
        [logo.leadingAnchor constraintEqualToAnchor:content.leadingAnchor constant:24],
        [logo.widthAnchor constraintEqualToConstant:54],
        [logo.heightAnchor constraintEqualToConstant:54],
        [title.topAnchor constraintEqualToAnchor:content.topAnchor constant:24],
        [title.leadingAnchor constraintEqualToAnchor:logo.trailingAnchor constant:12],
        [subtitle.topAnchor constraintEqualToAnchor:title.bottomAnchor constant:4],
        [subtitle.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],

        [self.recordingBox.topAnchor constraintEqualToAnchor:subtitle.bottomAnchor constant:20],
        [self.recordingBox.leadingAnchor constraintEqualToAnchor:content.leadingAnchor constant:24],
        [self.recordingBox.trailingAnchor constraintEqualToAnchor:content.trailingAnchor constant:-24],
        [self.recordingBox.heightAnchor constraintEqualToConstant:92],
        [self.fileLabel.leadingAnchor constraintEqualToAnchor:self.recordingBox.leadingAnchor constant:18],
        [self.fileLabel.topAnchor constraintEqualToAnchor:self.recordingBox.topAnchor constant:30],
        [self.fileLabel.trailingAnchor constraintLessThanOrEqualToAnchor:self.chooseButton.leadingAnchor constant:-12],
        [self.filePathLabel.leadingAnchor constraintEqualToAnchor:self.fileLabel.leadingAnchor],
        [self.filePathLabel.topAnchor constraintEqualToAnchor:self.fileLabel.bottomAnchor constant:4],
        [self.filePathLabel.trailingAnchor constraintLessThanOrEqualToAnchor:self.chooseButton.leadingAnchor constant:-12],
        [self.chooseButton.trailingAnchor constraintEqualToAnchor:self.recordingBox.trailingAnchor constant:-16],
        [self.chooseButton.centerYAnchor constraintEqualToAnchor:self.recordingBox.centerYAnchor constant:8],

        [languageLabel.topAnchor constraintEqualToAnchor:self.recordingBox.bottomAnchor constant:22],
        [languageLabel.leadingAnchor constraintEqualToAnchor:self.recordingBox.leadingAnchor],
        [languageLabel.widthAnchor constraintEqualToConstant:90],
        [self.languagePopup.centerYAnchor constraintEqualToAnchor:languageLabel.centerYAnchor],
        [self.languagePopup.leadingAnchor constraintEqualToAnchor:languageLabel.trailingAnchor constant:10],
        [self.languagePopup.widthAnchor constraintEqualToConstant:270],

        [speakerLabel.topAnchor constraintEqualToAnchor:languageLabel.bottomAnchor constant:18],
        [speakerLabel.leadingAnchor constraintEqualToAnchor:languageLabel.leadingAnchor],
        [speakerLabel.widthAnchor constraintEqualToAnchor:languageLabel.widthAnchor],
        [self.speakerCheckbox.centerYAnchor constraintEqualToAnchor:speakerLabel.centerYAnchor],
        [self.speakerCheckbox.leadingAnchor constraintEqualToAnchor:self.languagePopup.leadingAnchor],

        [saveLabel.topAnchor constraintEqualToAnchor:speakerLabel.bottomAnchor constant:18],
        [saveLabel.leadingAnchor constraintEqualToAnchor:languageLabel.leadingAnchor],
        [saveLabel.widthAnchor constraintEqualToAnchor:languageLabel.widthAnchor],
        [self.outputLabel.centerYAnchor constraintEqualToAnchor:saveLabel.centerYAnchor],
        [self.outputLabel.leadingAnchor constraintEqualToAnchor:self.languagePopup.leadingAnchor],
        [self.outputButton.leadingAnchor constraintEqualToAnchor:self.outputLabel.trailingAnchor constant:10],
        [self.outputButton.trailingAnchor constraintEqualToAnchor:self.recordingBox.trailingAnchor],
        [self.outputButton.widthAnchor constraintEqualToConstant:100],
        [self.outputButton.centerYAnchor constraintEqualToAnchor:saveLabel.centerYAnchor],

        [self.startButton.topAnchor constraintEqualToAnchor:saveLabel.bottomAnchor constant:24],
        [self.startButton.leadingAnchor constraintEqualToAnchor:languageLabel.leadingAnchor],
        [self.startButton.widthAnchor constraintEqualToConstant:120],
        [self.statusLabel.leadingAnchor constraintEqualToAnchor:self.startButton.trailingAnchor constant:18],
        [self.statusLabel.centerYAnchor constraintEqualToAnchor:self.startButton.centerYAnchor],
        [self.statusLabel.trailingAnchor constraintLessThanOrEqualToAnchor:self.showButton.leadingAnchor constant:-12],
        [self.showButton.trailingAnchor constraintEqualToAnchor:self.recordingBox.trailingAnchor],
        [self.showButton.centerYAnchor constraintEqualToAnchor:self.startButton.centerYAnchor],

        [self.fileProgressLabel.topAnchor constraintEqualToAnchor:self.startButton.bottomAnchor constant:18],
        [self.fileProgressLabel.leadingAnchor constraintEqualToAnchor:languageLabel.leadingAnchor],
        [self.fileProgressLabel.trailingAnchor constraintEqualToAnchor:self.recordingBox.trailingAnchor],
        [self.fileProgress.topAnchor constraintEqualToAnchor:self.fileProgressLabel.bottomAnchor constant:6],
        [self.fileProgress.leadingAnchor constraintEqualToAnchor:languageLabel.leadingAnchor],
        [self.fileProgress.trailingAnchor constraintEqualToAnchor:self.recordingBox.trailingAnchor],
        [self.overallProgressLabel.topAnchor constraintEqualToAnchor:self.fileProgress.bottomAnchor constant:12],
        [self.overallProgressLabel.leadingAnchor constraintEqualToAnchor:languageLabel.leadingAnchor],
        [self.overallProgressLabel.trailingAnchor constraintEqualToAnchor:self.recordingBox.trailingAnchor],
        [self.overallProgress.topAnchor constraintEqualToAnchor:self.overallProgressLabel.bottomAnchor constant:6],
        [self.overallProgress.leadingAnchor constraintEqualToAnchor:languageLabel.leadingAnchor],
        [self.overallProgress.trailingAnchor constraintEqualToAnchor:self.recordingBox.trailingAnchor],
        [self.timingLabel.topAnchor constraintEqualToAnchor:self.overallProgress.bottomAnchor constant:8],
        [self.timingLabel.leadingAnchor constraintEqualToAnchor:languageLabel.leadingAnchor],

        [self.logLabel.topAnchor constraintEqualToAnchor:self.timingLabel.bottomAnchor constant:18],
        [self.logLabel.leadingAnchor constraintEqualToAnchor:languageLabel.leadingAnchor],
        [self.logToggleButton.centerYAnchor constraintEqualToAnchor:self.logLabel.centerYAnchor],
        [self.logToggleButton.trailingAnchor constraintEqualToAnchor:self.recordingBox.trailingAnchor],
        [self.logScroll.topAnchor constraintEqualToAnchor:self.logLabel.bottomAnchor constant:6],
        [self.logScroll.leadingAnchor constraintEqualToAnchor:languageLabel.leadingAnchor],
        [self.logScroll.trailingAnchor constraintEqualToAnchor:self.recordingBox.trailingAnchor],
        [privacy.topAnchor constraintEqualToAnchor:self.logScroll.bottomAnchor constant:14],
        [privacy.leadingAnchor constraintEqualToAnchor:languageLabel.leadingAnchor],
        [privacy.bottomAnchor constraintLessThanOrEqualToAnchor:content.bottomAnchor constant:-20],
    ]];
    self.logHeightConstraint = [self.logScroll.heightAnchor constraintEqualToConstant:150];
    self.logHeightConstraint.active = YES;
    [self.window makeKeyAndOrderFront:nil];
}

- (void)toggleLogs:(id)sender {
    BOOL willHide = !self.logScroll.hidden;
    self.logScroll.hidden = willHide;
    self.logHeightConstraint.constant = willHide ? 0 : 150;
    self.logToggleButton.title = willHide ? @"Show Logs" : @"Hide Logs";
    [NSAnimationContext runAnimationGroup:^(NSAnimationContext *context) {
        context.duration = 0.18;
        [self.window.contentView layoutSubtreeIfNeeded];
    } completionHandler:nil];
}

- (NSArray<NSString *> *)supportedExtensions {
    return @[@"wav", @"mp3", @"m4a", @"aac", @"flac", @"ogg", @"mp4", @"mov", @"mkv", @"webm"];
}

- (NSArray<NSURL *> *)supportedURLsFromDraggingInfo:(id<NSDraggingInfo>)sender {
    NSDictionary *options = @{NSPasteboardURLReadingFileURLsOnlyKey: @YES};
    NSArray<NSURL *> *items = [sender.draggingPasteboard readObjectsForClasses:@[NSURL.class] options:options];
    NSSet<NSString *> *supported = [NSSet setWithArray:self.supportedExtensions];
    NSMutableArray<NSURL *> *accepted = [NSMutableArray array];
    NSMutableSet<NSString *> *seen = [NSMutableSet set];
    for (NSURL *url in items) {
        NSURL *clean = url.filePathURL.URLByStandardizingPath;
        NSString *extension = clean.pathExtension.lowercaseString;
        if (clean.isFileURL && [supported containsObject:extension] && ![seen containsObject:clean.path]) {
            [accepted addObject:clean];
            [seen addObject:clean.path];
        }
    }
    return accepted;
}

- (BOOL)canAcceptRecordingDrop:(id<NSDraggingInfo>)sender {
    return !self.task.isRunning && [self supportedURLsFromDraggingInfo:sender].count > 0;
}

- (BOOL)acceptRecordingDrop:(id<NSDraggingInfo>)sender {
    if (self.task.isRunning) return NO;
    NSArray<NSURL *> *urls = [self supportedURLsFromDraggingInfo:sender];
    if (!urls.count) {
        self.statusLabel.textColor = NSColor.systemRedColor;
        self.statusLabel.stringValue = @"Drop a supported audio or video recording.";
        return NO;
    }
    [self selectSourceURLs:urls];
    return YES;
}

- (void)selectSourceURLs:(NSArray<NSURL *> *)urls {
    self.sourceURLs = urls;
    NSUInteger count = self.sourceURLs.count;
    self.statusLabel.textColor = NSColor.secondaryLabelColor;
    if (count == 1) {
        NSURL *source = self.sourceURLs.firstObject;
        self.fileLabel.stringValue = source.lastPathComponent;
        self.filePathLabel.stringValue = source.URLByDeletingLastPathComponent.path;
        self.statusLabel.stringValue = [NSString stringWithFormat:@"Ready to transcribe %@.", source.lastPathComponent];
        self.startButton.title = @"Transcribe";
    } else {
        self.fileLabel.stringValue = [NSString stringWithFormat:@"%lu recordings selected", (unsigned long)count];
        self.filePathLabel.stringValue = [[self.sourceURLs valueForKey:@"lastPathComponent"] componentsJoinedByString:@", "];
        self.statusLabel.stringValue = [NSString stringWithFormat:@"Ready to transcribe %lu recordings.", (unsigned long)count];
        self.startButton.title = [NSString stringWithFormat:@"Transcribe %lu", (unsigned long)count];
    }
    self.startButton.enabled = YES;
    self.showButton.hidden = YES;
    self.resultURL = nil;
    self.fileProgress.doubleValue = 0;
    self.overallProgress.doubleValue = 0;
    self.fileProgressLabel.stringValue = @"Current recording • Waiting to start";
    self.overallProgressLabel.stringValue = @"Overall progress • 0%";
    self.timingLabel.stringValue = @"Estimated time will appear after transcription starts.";
}

- (void)chooseRecording:(id)sender {
    NSOpenPanel *panel = [NSOpenPanel openPanel];
    panel.title = @"Choose recordings";
    panel.prompt = @"Choose";
    panel.canChooseDirectories = NO;
    panel.allowsMultipleSelection = YES;
    NSMutableArray<UTType *> *types = [NSMutableArray array];
    for (NSString *extension in self.supportedExtensions) {
        UTType *type = [UTType typeWithFilenameExtension:extension];
        if (type) [types addObject:type];
    }
    panel.allowedContentTypes = types;
    if ([panel runModal] == NSModalResponseOK) {
        [self selectSourceURLs:panel.URLs];
    }
}

- (void)chooseOutput:(id)sender {
    NSOpenPanel *panel = [NSOpenPanel openPanel];
    panel.title = @"Choose where transcripts are saved";
    panel.prompt = @"Choose";
    panel.canChooseFiles = NO;
    panel.canChooseDirectories = YES;
    panel.canCreateDirectories = YES;
    panel.directoryURL = self.outputURL;
    if ([panel runModal] == NSModalResponseOK) {
        self.outputURL = panel.URL;
        self.outputLabel.stringValue = self.outputURL.path;
    }
}

- (double)probeDurationForURL:(NSURL *)url {
    NSTask *probe = [[NSTask alloc] init];
    probe.launchPath = @"/usr/bin/env";
    probe.arguments = @[@"ffprobe", @"-v", @"error", @"-show_entries", @"format=duration",
        @"-of", @"default=noprint_wrappers=1:nokey=1", url.path];
    NSMutableDictionary *environment = [NSProcessInfo.processInfo.environment mutableCopy];
    environment[@"PATH"] = @"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";
    probe.environment = environment;
    NSPipe *output = [NSPipe pipe];
    probe.standardOutput = output;
    probe.standardError = [NSPipe pipe];
    NSError *error = nil;
    if (![probe launchAndReturnError:&error]) return 60;
    [probe waitUntilExit];
    if (probe.terminationStatus != 0) return 60;
    NSData *data = [output.fileHandleForReading readDataToEndOfFile];
    NSString *text = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
    double duration = text.doubleValue;
    return isfinite(duration) && duration > 0 ? duration : 60;
}

- (double)historicalProcessingRatioWithSpeakers:(BOOL)speakers {
    NSFileManager *files = NSFileManager.defaultManager;
    NSArray<NSURL *> *items = [files contentsOfDirectoryAtURL:self.outputURL
        includingPropertiesForKeys:nil options:NSDirectoryEnumerationSkipsHiddenFiles error:nil];
    double audioTotal = 0;
    double workTotal = 0;
    for (NSURL *item in items) {
        NSURL *jobURL = [item URLByAppendingPathComponent:@"job.json"];
        NSURL *sourceURL = [item URLByAppendingPathComponent:@"source-metadata.json"];
        NSData *jobData = [NSData dataWithContentsOfURL:jobURL];
        NSData *sourceData = [NSData dataWithContentsOfURL:sourceURL];
        if (!jobData || !sourceData) continue;
        NSDictionary *job = [NSJSONSerialization JSONObjectWithData:jobData options:0 error:nil];
        NSDictionary *source = [NSJSONSerialization JSONObjectWithData:sourceData options:0 error:nil];
        if (![job[@"status"] isEqualToString:@"completed"] || [job[@"recipe"][@"speakers"] boolValue] != speakers) continue;
        double audio = [source[@"source"][@"duration_seconds"] doubleValue];
        double work = 0;
        for (NSDictionary *stage in [job[@"stages"] allValues]) {
            if ([stage[@"status"] isEqualToString:@"succeeded"]) work += [stage[@"duration_seconds"] doubleValue];
        }
        double ratio = audio > 0 ? work / audio : 0;
        if (audio >= 5 && ratio >= 0.01 && ratio <= 5) {
            audioTotal += audio;
            workTotal += work;
        }
    }
    if (audioTotal >= 30) return workTotal / audioTotal;
    return speakers ? 0.65 : 0.20;
}

- (NSArray<NSNumber *> *)stageRange:(NSString *)stage {
    BOOL speakers = self.speakerCheckbox.state == NSControlStateValueOn;
    NSDictionary *ranges = speakers ? @{
        @"inspect": @[@0.00, @0.01], @"normalize": @[@0.01, @0.06],
        @"whisper": @[@0.06, @0.46], @"canonical": @[@0.46, @0.48],
        @"diarization": @[@0.48, @0.97], @"align": @[@0.97, @1.00]
    } : @{
        @"inspect": @[@0.00, @0.02], @"normalize": @[@0.02, @0.10],
        @"whisper": @[@0.10, @0.95], @"canonical": @[@0.95, @1.00]
    };
    return ranges[stage] ?: @[@0.00, @0.01];
}

- (NSString *)shortDuration:(NSTimeInterval)seconds {
    NSInteger rounded = MAX(0, (NSInteger)llround(seconds));
    if (rounded < 60) return [NSString stringWithFormat:@"%lds", (long)rounded];
    NSInteger minutes = rounded / 60;
    if (minutes < 60) return [NSString stringWithFormat:@"%ldm", (long)minutes];
    return [NSString stringWithFormat:@"%ldh %ldm", (long)(minutes / 60), (long)(minutes % 60)];
}

- (void)updateProgressDisplay:(NSTimer *)timer {
    if (!self.batchStartedAt || !self.batchEstimates.count) return;
    double currentFraction = self.fileProgress.doubleValue / 100.0;
    if (self.task.isRunning && self.currentStage.length && self.stageStartedAt) {
        double estimate = self.batchEstimates[self.batchIndex].doubleValue;
        double expectedStage = MAX(1, estimate * (self.currentStageEndFraction - self.currentStageStartFraction));
        double stageElapsed = -self.stageStartedAt.timeIntervalSinceNow;
        double stageFraction = MIN(0.94, 0.75 * stageElapsed / expectedStage);
        double dynamic = self.currentStageStartFraction +
            (self.currentStageEndFraction - self.currentStageStartFraction) * stageFraction;
        currentFraction = MAX(currentFraction, dynamic);
        self.fileProgress.doubleValue = currentFraction * 100;
    }
    double total = 0;
    double done = 0;
    for (NSUInteger index = 0; index < self.batchEstimates.count; index++) {
        double estimate = self.batchEstimates[index].doubleValue;
        total += estimate;
        if (index < self.batchIndex) done += estimate;
        else if (index == self.batchIndex && self.batchIndex < self.batchURLs.count) done += estimate * currentFraction;
    }
    double overallFraction = total > 0 ? MIN(1, done / total) : 0;
    self.overallProgress.doubleValue = overallFraction * 100;
    if (self.batchIndex < self.batchURLs.count) {
        NSString *name = self.batchURLs[self.batchIndex].lastPathComponent;
        self.fileProgressLabel.stringValue = [NSString stringWithFormat:@"Recording %lu of %lu • %@ • %.0f%%",
            (unsigned long)(self.batchIndex + 1), (unsigned long)self.batchURLs.count, name, currentFraction * 100];
    }
    self.overallProgressLabel.stringValue = [NSString stringWithFormat:@"Overall progress • %.0f%%", overallFraction * 100];
    NSTimeInterval elapsed = -self.batchStartedAt.timeIntervalSinceNow;
    double adjustedTotal = total;
    if (overallFraction >= 0.03) adjustedTotal = MAX(total, elapsed / overallFraction);
    NSTimeInterval remaining = MAX(0, adjustedTotal - elapsed);
    NSString *remainingText = remaining < 60 ? @"Less than a minute remaining" :
        [NSString stringWithFormat:@"Approximately %@ remaining", [self shortDuration:remaining]];
    self.timingLabel.stringValue = [NSString stringWithFormat:@"Elapsed %@ • %@",
        [self shortDuration:elapsed], remainingText];
}

- (void)startTranscription:(id)sender {
    if (!self.sourceURLs.count || self.task.isRunning) return;
    NSURL *backend = [[NSBundle mainBundle] URLForResource:@"transcribe" withExtension:@"py" subdirectory:@"backend"];
    if (!backend) {
        [self failUI:@"The transcription backend is missing from the app."];
        return;
    }
    NSFileManager *files = NSFileManager.defaultManager;
    NSString *model = [NSHomeDirectory() stringByAppendingPathComponent:
        @"Library/Application Support/Local Transcriber/models/ggml-medium.bin"];
    if (![files fileExistsAtPath:model]) {
        [self failUI:@"Setup is incomplete. Run Install Local Transcriber.command, then reopen the app."];
        return;
    }
    if (![self backendPythonPath]) {
        [self failUI:@"Python is missing. Run Install Local Transcriber.command, then reopen the app."];
        return;
    }
    if (self.speakerCheckbox.state == NSControlStateValueOn) {
        NSString *python = [NSHomeDirectory() stringByAppendingPathComponent:
            @"Library/Application Support/Local Transcriber/pyannote-env/bin/python"];
        if (![files isExecutableFileAtPath:python]) {
            [self failUI:@"Speaker separation is not installed. Run the installer again or turn it off."];
            return;
        }
    }
    self.batchURLs = [self.sourceURLs copy];
    self.resultURLs = [NSMutableArray array];
    self.readableResultURLs = [NSMutableArray array];
    self.batchIndex = 0;
    self.succeededCount = 0;
    self.failedCount = 0;
    self.batchDurations = [NSMutableArray array];
    self.batchEstimates = [NSMutableArray array];
    double ratio = [self historicalProcessingRatioWithSpeakers:self.speakerCheckbox.state == NSControlStateValueOn];
    for (NSURL *source in self.batchURLs) {
        double duration = [self probeDurationForURL:source];
        [self.batchDurations addObject:@(duration)];
        [self.batchEstimates addObject:@(MAX(10, duration * ratio + 8))];
    }
    self.batchStartedAt = NSDate.date;
    self.fileStartedAt = nil;
    self.stageStartedAt = nil;
    self.currentStage = nil;
    self.fileProgress.doubleValue = 0;
    self.overallProgress.doubleValue = 0;
    self.fileProgressLabel.hidden = NO;
    self.fileProgress.hidden = NO;
    self.overallProgressLabel.hidden = NO;
    self.overallProgress.hidden = NO;
    self.timingLabel.hidden = NO;
    self.resultURL = nil;
    self.readableResultsURL = [self createReadableResultsFolder];
    self.logView.string = @"";
    [self.stdoutBuffer setString:@""];
    self.startButton.enabled = NO;
    self.chooseButton.enabled = NO;
    self.outputButton.enabled = NO;
    self.languagePopup.enabled = NO;
    self.speakerCheckbox.enabled = NO;
    self.showButton.hidden = YES;
    self.statusLabel.textColor = NSColor.secondaryLabelColor;
    [self.progressTimer invalidate];
    self.progressTimer = [NSTimer scheduledTimerWithTimeInterval:0.5 target:self
        selector:@selector(updateProgressDisplay:) userInfo:nil repeats:YES];
    [self startNextTranscriptionWithBackend:backend];
}

- (void)startNextTranscriptionWithBackend:(NSURL *)backend {
    if (self.batchIndex >= self.batchURLs.count) {
        [self finishBatch];
        return;
    }
    NSURL *sourceURL = self.batchURLs[self.batchIndex];
    self.fileStartedAt = NSDate.date;
    self.stageStartedAt = NSDate.date;
    self.currentStage = @"starting";
    self.currentStageStartFraction = 0;
    self.currentStageEndFraction = 0.01;
    self.currentFileDidWork = NO;
    self.fileProgress.doubleValue = 0;
    [self updateProgressDisplay:nil];
    [[NSFileManager defaultManager] createDirectoryAtURL:self.outputURL withIntermediateDirectories:YES attributes:nil error:nil];
    NSArray *languages = @[@"auto", @"en", @"fr"];
    NSMutableArray *arguments = [NSMutableArray arrayWithArray:@[
        [self backendPythonPath], backend.path, sourceURL.path,
        @"--output-root", self.outputURL.path,
        @"--language", languages[self.languagePopup.indexOfSelectedItem]
    ]];
    if (self.speakerCheckbox.state == NSControlStateValueOn) {
        [arguments addObject:@"--speakers"];
        NSString *python = [NSHomeDirectory() stringByAppendingPathComponent:
            @"Library/Application Support/Local Transcriber/pyannote-env/bin/python"];
        [arguments addObjectsFromArray:@[@"--diarization-python", python]];
    }
    self.task = [[NSTask alloc] init];
    self.task.launchPath = @"/usr/bin/env";
    self.task.arguments = arguments;
    NSMutableDictionary *environment = [NSProcessInfo.processInfo.environment mutableCopy];
    environment[@"PATH"] = @"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";
    environment[@"PYTHONUNBUFFERED"] = @"1";
    environment[@"PYTHONDONTWRITEBYTECODE"] = @"1";
    environment[@"PYANNOTE_METRICS_ENABLED"] = @"0";
    environment[@"HF_HUB_OFFLINE"] = @"1";
    self.task.environment = environment;
    NSPipe *stdoutPipe = [NSPipe pipe];
    NSPipe *stderrPipe = [NSPipe pipe];
    self.task.standardOutput = stdoutPipe;
    self.task.standardError = stderrPipe;
    __weak typeof(self) weakSelf = self;
    stdoutPipe.fileHandleForReading.readabilityHandler = ^(NSFileHandle *handle) {
        NSData *data = handle.availableData;
        if (!data.length) return;
        NSString *text = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
        dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf consumeStdout:text]; });
    };
    stderrPipe.fileHandleForReading.readabilityHandler = ^(NSFileHandle *handle) {
        NSData *data = handle.availableData;
        if (!data.length) return;
        NSString *text = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
        dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf appendLog:text]; });
    };
    self.task.terminationHandler = ^(NSTask *task) {
        dispatch_async(dispatch_get_main_queue(), ^{
            stdoutPipe.fileHandleForReading.readabilityHandler = nil;
            stderrPipe.fileHandleForReading.readabilityHandler = nil;
            if (task.terminationStatus == 0) {
                weakSelf.succeededCount += 1;
            } else {
                weakSelf.failedCount += 1;
                [weakSelf appendLog:[NSString stringWithFormat:@"\nERROR: %@ could not be transcribed.\n", sourceURL.lastPathComponent]];
            }
            weakSelf.task = nil;
            weakSelf.batchIndex += 1;
            [weakSelf startNextTranscriptionWithBackend:backend];
        });
    };
    [self.stdoutBuffer setString:@""];
    self.statusLabel.textColor = NSColor.secondaryLabelColor;
    self.statusLabel.stringValue = [NSString stringWithFormat:@"[%lu of %lu] Starting %@…",
        (unsigned long)(self.batchIndex + 1), (unsigned long)self.batchURLs.count, sourceURL.lastPathComponent];
    [self appendLog:[NSString stringWithFormat:@"\n=== %lu of %lu: %@ ===\n",
        (unsigned long)(self.batchIndex + 1), (unsigned long)self.batchURLs.count, sourceURL.path]];
    NSError *error = nil;
    if (![self.task launchAndReturnError:&error]) {
        self.task = nil;
        self.failedCount += 1;
        [self appendLog:[NSString stringWithFormat:@"ERROR: %@\n", error.localizedDescription]];
        self.batchIndex += 1;
        [self startNextTranscriptionWithBackend:backend];
    }
}

- (void)finishBatch {
    [self.progressTimer invalidate];
    self.progressTimer = nil;
    self.fileProgress.doubleValue = 100;
    self.overallProgress.doubleValue = 100;
    self.overallProgressLabel.stringValue = @"Overall progress • 100%";
    NSTimeInterval elapsed = self.batchStartedAt ? -self.batchStartedAt.timeIntervalSinceNow : 0;
    self.timingLabel.stringValue = [NSString stringWithFormat:@"Elapsed %@ • Complete", [self shortDuration:elapsed]];
    self.startButton.enabled = self.sourceURLs.count > 0;
    self.chooseButton.enabled = YES;
    self.outputButton.enabled = YES;
    self.languagePopup.enabled = YES;
    self.speakerCheckbox.enabled = YES;
    self.showButton.hidden = self.resultURLs.count == 0;
    if (self.readableResultURLs.count == 1) self.resultURL = self.readableResultURLs.firstObject;
    else if (self.readableResultURLs.count > 1) self.resultURL = self.readableResultsURL;
    else if (self.resultURLs.count == 1) self.resultURL = self.resultURLs.firstObject;
    else if (self.resultURLs.count > 1) self.resultURL = self.outputURL;
    if (self.failedCount == 0) {
        self.statusLabel.textColor = NSColor.secondaryLabelColor;
        self.statusLabel.stringValue = self.succeededCount == 1 ? @"Transcription complete." :
            [NSString stringWithFormat:@"All %lu transcriptions complete.", (unsigned long)self.succeededCount];
    } else {
        self.statusLabel.textColor = NSColor.systemRedColor;
        self.statusLabel.stringValue = [NSString stringWithFormat:@"%lu complete, %lu failed. See the technical log.",
            (unsigned long)self.succeededCount, (unsigned long)self.failedCount];
    }
    self.batchURLs = nil;
}

- (void)appendLog:(NSString *)text {
    if (!text.length) return;
    NSDictionary *attributes = @{
        NSForegroundColorAttributeName: NSColor.whiteColor,
        NSFontAttributeName: [NSFont monospacedSystemFontOfSize:11 weight:NSFontWeightRegular]
    };
    [[self.logView textStorage] appendAttributedString:
        [[NSAttributedString alloc] initWithString:text attributes:attributes]];
    [self.logView scrollRangeToVisible:NSMakeRange(self.logView.string.length, 0)];
}

- (void)consumeStdout:(NSString *)text {
    [self appendLog:text];
    [self.stdoutBuffer appendString:text];
    NSArray *lines = [self.stdoutBuffer componentsSeparatedByString:@"\n"];
    [self.stdoutBuffer setString:lines.lastObject ?: @""];
    for (NSUInteger index = 0; index + 1 < lines.count; index++) {
        NSData *data = [lines[index] dataUsingEncoding:NSUTF8StringEncoding];
        NSDictionary *event = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        if (![event isKindOfClass:NSDictionary.class]) continue;
        NSString *kind = event[@"event"];
        if ([kind isEqualToString:@"stage"]) {
            NSString *stageName = event[@"stage"];
            NSString *stageStatus = event[@"status"];
            NSArray<NSNumber *> *range = [self stageRange:stageName];
            if ([stageStatus isEqualToString:@"running"]) {
                self.currentStage = stageName;
                self.stageStartedAt = NSDate.date;
                self.currentStageStartFraction = range[0].doubleValue;
                self.currentStageEndFraction = range[1].doubleValue;
                self.currentFileDidWork = YES;
                self.fileProgress.doubleValue = MAX(self.fileProgress.doubleValue,
                    self.currentStageStartFraction * 100);
            } else if ([stageStatus isEqualToString:@"cached"] || [stageStatus isEqualToString:@"succeeded"]) {
                self.fileProgress.doubleValue = MAX(self.fileProgress.doubleValue, range[1].doubleValue * 100);
                self.currentStage = nil;
                self.stageStartedAt = nil;
            }
            NSString *stage = [self stageLabel:stageName status:stageStatus];
            self.statusLabel.stringValue = [NSString stringWithFormat:@"[%lu of %lu] %@",
                (unsigned long)(self.batchIndex + 1), (unsigned long)self.batchURLs.count, stage];
            [self updateProgressDisplay:nil];
        } else if ([kind isEqualToString:@"completed"]) {
            self.fileProgress.doubleValue = 100;
            self.currentStage = nil;
            self.stageStartedAt = nil;
            [self updateProgressDisplay:nil];
            NSURL *result = [NSURL fileURLWithPath:event[@"output_directory"]];
            [self.resultURLs addObject:result];
            self.resultURL = result;
            if (self.batchIndex < self.batchURLs.count && self.readableResultsURL) {
                NSURL *readable = [self createReadableResultFromJob:result source:self.batchURLs[self.batchIndex]];
                if (readable) [self.readableResultURLs addObject:readable];
            }
        } else if ([kind isEqualToString:@"failed"]) {
            self.statusLabel.textColor = NSColor.systemRedColor;
            self.statusLabel.stringValue = event[@"message"] ?: @"Transcription failed.";
        }
    }
}

- (NSURL *)createReadableResultsFolder {
    NSFileManager *files = NSFileManager.defaultManager;
    [files createDirectoryAtURL:self.outputURL withIntermediateDirectories:YES attributes:nil error:nil];
    NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
    formatter.locale = [NSLocale localeWithLocaleIdentifier:@"en_CA_POSIX"];
    formatter.dateFormat = @"yyyy-MM-dd 'at' HH.mm.ss";
    NSString *base = [NSString stringWithFormat:@"Transcripts %@", [formatter stringFromDate:NSDate.date]];
    NSURL *folder = [self.outputURL URLByAppendingPathComponent:base isDirectory:YES];
    NSUInteger suffix = 2;
    while ([files fileExistsAtPath:folder.path]) {
        folder = [self.outputURL URLByAppendingPathComponent:
            [NSString stringWithFormat:@"%@ (%lu)", base, (unsigned long)suffix++] isDirectory:YES];
    }
    NSError *error = nil;
    if (![files createDirectoryAtURL:folder withIntermediateDirectories:YES attributes:nil error:&error]) {
        [self appendLog:[NSString stringWithFormat:@"WARNING: Could not create the simple results folder: %@\n", error.localizedDescription]];
        return nil;
    }
    NSString *guide = @"LOCAL TRANSCRIBER RESULTS\n\n"
        "Each recording has its own folder.\n\n"
        "Transcript.txt is the main file to read. When speaker separation was enabled, it includes anonymous speaker labels.\n\n"
        "Subtitles.srt contains timed captions for compatible video players and editors.\n\n"
        "The Local Transcriber folder also retains technical processing files so interrupted work can resume safely. You normally do not need to open those files.\n";
    [guide writeToURL:[folder URLByAppendingPathComponent:@"README - Start Here.txt"]
        atomically:YES encoding:NSUTF8StringEncoding error:nil];
    return folder;
}

- (NSString *)safeResultNameForSource:(NSURL *)source {
    NSString *name = source.lastPathComponent.stringByDeletingPathExtension;
    NSCharacterSet *forbidden = [NSCharacterSet characterSetWithCharactersInString:@"/:\\"];
    name = [[name componentsSeparatedByCharactersInSet:forbidden] componentsJoinedByString:@"-"];
    name = [name stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    if (!name.length) name = @"Recording";
    if (name.length > 120) name = [name substringToIndex:120];
    return name;
}

- (NSURL *)createReadableResultFromJob:(NSURL *)job source:(NSURL *)source {
    NSFileManager *files = NSFileManager.defaultManager;
    NSString *base = [self safeResultNameForSource:source];
    NSURL *folder = [self.readableResultsURL URLByAppendingPathComponent:base isDirectory:YES];
    NSUInteger suffix = 2;
    while ([files fileExistsAtPath:folder.path]) {
        folder = [self.readableResultsURL URLByAppendingPathComponent:
            [NSString stringWithFormat:@"%@ (%lu)", base, (unsigned long)suffix++] isDirectory:YES];
    }
    NSError *error = nil;
    if (![files createDirectoryAtURL:folder withIntermediateDirectories:YES attributes:nil error:&error]) {
        [self appendLog:[NSString stringWithFormat:@"WARNING: Could not organize the readable transcript: %@\n", error.localizedDescription]];
        return nil;
    }
    NSURL *speakerTranscript = [job URLByAppendingPathComponent:@"transcript-with-speakers.txt"];
    NSURL *plainTranscript = [job URLByAppendingPathComponent:@"transcript.txt"];
    NSURL *preferred = [files fileExistsAtPath:speakerTranscript.path] ? speakerTranscript : plainTranscript;
    if (![files copyItemAtURL:preferred toURL:[folder URLByAppendingPathComponent:@"Transcript.txt"] error:&error]) {
        [self appendLog:[NSString stringWithFormat:@"WARNING: Could not copy the readable transcript: %@\n", error.localizedDescription]];
        return nil;
    }
    NSURL *subtitles = [job URLByAppendingPathComponent:@"raw-transcript.srt"];
    if ([files fileExistsAtPath:subtitles.path]) {
        [files copyItemAtURL:subtitles toURL:[folder URLByAppendingPathComponent:@"Subtitles.srt"] error:nil];
    }
    return folder;
}

- (NSString *)stageLabel:(NSString *)stage status:(NSString *)status {
    NSDictionary *labels = @{
        @"inspect": @"Inspecting recording", @"normalize": @"Preparing audio",
        @"whisper": @"Transcribing English/French speech", @"canonical": @"Building timestamped transcript",
        @"diarization": @"Detecting speakers", @"align": @"Combining speakers with transcript"
    };
    NSString *label = labels[stage] ?: stage.capitalizedString;
    return [status isEqualToString:@"cached"] ? [label stringByAppendingString:@" — already complete"] : [label stringByAppendingString:@"…"];
}

- (void)failUI:(NSString *)message {
    self.statusLabel.textColor = NSColor.systemRedColor;
    self.statusLabel.stringValue = message;
    self.startButton.enabled = self.sourceURLs.count > 0;
}

- (void)showResults:(id)sender {
    if (self.resultURL) [[NSWorkspace sharedWorkspace] selectFile:nil inFileViewerRootedAtPath:self.resultURL.path];
}

@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *application = [NSApplication sharedApplication];
        application.activationPolicy = NSApplicationActivationPolicyRegular;
        AppDelegate *delegate = [[AppDelegate alloc] init];
        application.delegate = delegate;
        [application run];
    }
    return 0;
}

\n