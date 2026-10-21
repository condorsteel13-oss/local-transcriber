#import <Cocoa/Cocoa.h>

static NSColor *Color(CGFloat r, CGFloat g, CGFloat b, CGFloat a) {
    return [NSColor colorWithSRGBRed:r / 255.0 green:g / 255.0 blue:b / 255.0 alpha:a];
}

static void RoundedBar(CGFloat x, CGFloat y, CGFloat width, CGFloat height, NSColor *color) {
    NSBezierPath *bar = [NSBezierPath bezierPathWithRoundedRect:NSMakeRect(x, y, width, height)
                                                        xRadius:width / 2 yRadius:width / 2];
    [color setFill];
    [bar fill];
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) {
            fprintf(stderr, "usage: generate_icon output.png\n");
            return 2;
        }

        const CGFloat size = 1024.0;
        NSImage *image = [[NSImage alloc] initWithSize:NSMakeSize(size, size)];
        [image lockFocus];
        [[NSColor clearColor] setFill];
        NSRectFill(NSMakeRect(0, 0, size, size));

        NSRect tileRect = NSMakeRect(64, 64, 896, 896);
        NSBezierPath *tile = [NSBezierPath bezierPathWithRoundedRect:tileRect xRadius:210 yRadius:210];
        NSGradient *background = [[NSGradient alloc]
            initWithStartingColor:Color(20, 139, 166, 1)
            endingColor:Color(45, 61, 116, 1)];
        [background drawInBezierPath:tile angle:-55];

        // A quiet inner highlight keeps the icon readable in both Finder themes.
        NSBezierPath *highlight = [NSBezierPath bezierPathWithRoundedRect:NSMakeRect(90, 470, 844, 454)
                                                                  xRadius:170 yRadius:170];
        [Color(255, 255, 255, 0.055) setFill];
        [highlight fill];

        // Speech bubble: transcription/conversation.
        NSBezierPath *bubble = [NSBezierPath bezierPath];
        [bubble moveToPoint:NSMakePoint(276, 760)];
        [bubble curveToPoint:NSMakePoint(202, 686) controlPoint1:NSMakePoint(235, 760) controlPoint2:NSMakePoint(202, 727)];
        [bubble lineToPoint:NSMakePoint(202, 390)];
        [bubble curveToPoint:NSMakePoint(276, 316) controlPoint1:NSMakePoint(202, 349) controlPoint2:NSMakePoint(235, 316)];
        [bubble lineToPoint:NSMakePoint(400, 316)];
        [bubble lineToPoint:NSMakePoint(354, 222)];
        [bubble lineToPoint:NSMakePoint(492, 316)];
        [bubble lineToPoint:NSMakePoint(748, 316)];
        [bubble curveToPoint:NSMakePoint(822, 390) controlPoint1:NSMakePoint(789, 316) controlPoint2:NSMakePoint(822, 349)];
        [bubble lineToPoint:NSMakePoint(822, 686)];
        [bubble curveToPoint:NSMakePoint(748, 760) controlPoint1:NSMakePoint(822, 727) controlPoint2:NSMakePoint(789, 760)];
        [bubble closePath];

        NSShadow *shadow = [[NSShadow alloc] init];
        shadow.shadowColor = Color(5, 20, 45, 0.28);
        shadow.shadowBlurRadius = 24;
        shadow.shadowOffset = NSMakeSize(0, -12);
        [NSGraphicsContext saveGraphicsState];
        [shadow set];
        [Color(247, 251, 253, 1) setFill];
        [bubble fill];
        [NSGraphicsContext restoreGraphicsState];

        // Waveform: audio becoming text. Rounded bars remain clear at 16 px.
        NSArray<NSNumber *> *heights = @[@110, @190, @282, @350, @282, @190, @110];
        CGFloat barWidth = 44;
        CGFloat gap = 28;
        CGFloat total = heights.count * barWidth + (heights.count - 1) * gap;
        CGFloat x = (size - total) / 2;
        NSArray<NSColor *> *colors = @[
            Color(33, 148, 176, 1), Color(31, 142, 174, 1), Color(38, 126, 168, 1),
            Color(61, 100, 157, 1), Color(78, 86, 151, 1), Color(91, 78, 146, 1),
            Color(99, 75, 143, 1)
        ];
        for (NSUInteger index = 0; index < heights.count; index++) {
            CGFloat height = heights[index].doubleValue;
            RoundedBar(x, 538 - height / 2, barWidth, height, colors[index]);
            x += barWidth + gap;
        }

        [image unlockFocus];
        CGImageRef cgImage = [image CGImageForProposedRect:NULL context:nil hints:nil];
        NSBitmapImageRep *bitmap = [[NSBitmapImageRep alloc] initWithCGImage:cgImage];
        NSData *png = [bitmap representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
        if (![png writeToFile:[NSString stringWithUTF8String:argv[1]] atomically:YES]) {
            fprintf(stderr, "failed to write icon\n");
            return 1;
        }
    }
    return 0;
}

\n