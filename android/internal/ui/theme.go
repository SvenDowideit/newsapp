package ui

import (
	"github.com/go-drift/drift/pkg/graphics"
	"github.com/go-drift/drift/pkg/theme"
)

var (
	colorBlack = graphics.RGB(0, 0, 0)
	colorWhite = graphics.RGB(255, 255, 255)
	colorGray  = graphics.RGB(80, 80, 80)

	bodyFontSize float64 = 18
	headFontSize float64 = 22
	metaFontSize float64 = 14
	pagePadding  float64 = 16
)

// EinkTheme returns a high-contrast light ThemeData suitable for eink displays.
func EinkTheme() *theme.ThemeData {
	return theme.DefaultLightTheme()
}

func HeadlineStyle() graphics.TextStyle {
	return graphics.TextStyle{
		Color:      colorBlack,
		FontSize:   headFontSize,
		FontWeight: graphics.FontWeightBold,
	}
}

func BodyStyle() graphics.TextStyle {
	return graphics.TextStyle{
		Color:    colorBlack,
		FontSize: bodyFontSize,
	}
}

func MetaStyle() graphics.TextStyle {
	return graphics.TextStyle{
		Color:    colorGray,
		FontSize: metaFontSize,
	}
}

func BoldBodyStyle() graphics.TextStyle {
	return graphics.TextStyle{
		Color:      colorBlack,
		FontSize:   bodyFontSize,
		FontWeight: graphics.FontWeightBold,
	}
}
