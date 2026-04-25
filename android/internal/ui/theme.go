package ui

import "github.com/go-drift/drift"

// EinkTheme is optimised for eink displays:
// pure black/white, large text, no animations.
var EinkTheme = drift.Theme{
	Background:   drift.ColorRGB(255, 255, 255),
	Foreground:   drift.ColorRGB(0, 0, 0),
	Accent:       drift.ColorRGB(0, 0, 0),
	FontSizeBody: 18,
	FontSizeHead: 22,
	Padding:      drift.Insets{Top: 16, Right: 16, Bottom: 16, Left: 16},
}

// StatusStyle returns text style for a breaking-news badge.
func StatusStyle() drift.TextStyle {
	return drift.TextStyle{
		Size:   14,
		Bold:   true,
		Color:  drift.ColorRGB(255, 255, 255),
		BgColor: drift.ColorRGB(0, 0, 0),
	}
}

// HeadlineStyle returns text style for item headlines.
func HeadlineStyle() drift.TextStyle {
	return drift.TextStyle{
		Size: EinkTheme.FontSizeHead,
		Bold: true,
	}
}

// BodyStyle returns text style for summary/body text.
func BodyStyle() drift.TextStyle {
	return drift.TextStyle{
		Size: EinkTheme.FontSizeBody,
	}
}

// MetaStyle is smaller grey text for metadata (source, date).
func MetaStyle() drift.TextStyle {
	return drift.TextStyle{
		Size:  14,
		Color: drift.ColorRGB(80, 80, 80),
	}
}
