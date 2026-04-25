package ui

import (
	"github.com/go-drift/drift/pkg/core"
	"github.com/go-drift/drift/pkg/layout"
	"github.com/go-drift/drift/pkg/widgets"
)

type menuEntry struct {
	label  string
	action string
}

var defaultMenuItems = []menuEntry{
	{"Save / bookmark", "save"},
	{"Send link", "send"},
	{"More like this  +", "interest_up"},
	{"Less like this  −", "interest_down"},
	{"Discard", "discard"},
	{"Close menu", "close"},
}

// ContextMenu renders a full-page menu.
func ContextMenu(onAction func(string)) core.Widget {
	items := make([]core.Widget, 0, len(defaultMenuItems)*2)
	for _, mi := range defaultMenuItems {
		action := mi.action
		label := mi.label
		items = append(items,
			widgets.GestureDetector{
				OnTap: func() { onAction(action) },
				Child: widgets.Padding{
					Padding: layout.EdgeInsetsSymmetric(pagePadding, 20),
					Child:   widgets.Text{Content: label, Style: BodyStyle()},
				},
			},
			widgets.Divider{},
		)
	}

	return widgets.Container{
		Child: widgets.Column{Children: items},
	}
}
