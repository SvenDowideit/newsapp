package ui

import (
	"github.com/go-drift/drift"
)

// ContextMenuItem is a single menu entry.
type ContextMenuItem struct {
	Label   string
	Action  string
}

var defaultMenuItems = []ContextMenuItem{
	{Label: "Save / bookmark", Action: "save"},
	{Label: "Send link", Action: "send"},
	{Label: "More like this", Action: "interest_up"},
	{Label: "Less like this", Action: "interest_down"},
	{Label: "Discard", Action: "discard"},
	{Label: "Close menu", Action: "close"},
}

// ContextMenu renders a full-screen overlay menu.
// onAction is called with the action string of the selected item.
func ContextMenu(onAction func(string)) drift.Widget {
	items := make([]drift.Widget, 0, len(defaultMenuItems))
	for _, mi := range defaultMenuItems {
		action := mi.Action
		label := mi.Label
		items = append(items,
			drift.GestureDetector(
				drift.Padding(
					drift.Text(label, BodyStyle()),
					drift.Insets{Top: 20, Bottom: 20, Left: 16, Right: 16},
				),
				drift.GestureCallbacks{
					OnTap: func() { onAction(action) },
				},
			),
		)
		items = append(items, drift.Divider())
	}

	return drift.Container(
		drift.Column(items),
		drift.ContainerOptions{
			Color: drift.ColorRGB(255, 255, 255),
			Border: drift.Border{Width: 1, Color: drift.ColorRGB(0, 0, 0)},
		},
	)
}
