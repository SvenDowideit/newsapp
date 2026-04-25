package ui

import (
	"fmt"
	"strings"

	"github.com/go-drift/drift"
	"github.com/svenDowideit/newsapp/internal/api/models"
)

// FeedPage renders the list of items in the feed.
// onSelect is called with the item index when an item is tapped.
func FeedPage(items []models.ClusterItem, onSelect func(int)) drift.Widget {
	if len(items) == 0 {
		return drift.Center(
			drift.Text("Loading feed…", BodyStyle()),
		)
	}

	rows := make([]drift.Widget, 0, len(items))
	for i, item := range items {
		idx := i
		it := item

		badge := drift.Empty()
		if it.IsBreaking {
			badge = drift.Padding(
				drift.Text("BREAKING", StatusStyle()),
				drift.Insets{Right: 8},
			)
		}

		sourceStr := strings.Join(it.SourceIDs, ", ")
		if len(it.SourceIDs) == 0 {
			sourceStr = "unknown"
		}

		row := drift.GestureDetector(
			drift.Column([]drift.Widget{
				drift.Row([]drift.Widget{badge, drift.Text(it.Headline, HeadlineStyle())}),
				drift.Text(it.Summary, BodyStyle()),
				drift.Text(fmt.Sprintf("%s · %d sources", sourceStr, it.ItemCount), MetaStyle()),
				drift.Divider(),
			}),
			drift.GestureCallbacks{
				OnTap: func() { onSelect(idx) },
			},
		)
		rows = append(rows, row)
	}

	return drift.ScrollView(
		drift.Column(rows),
		drift.ScrollViewOptions{Disabled: false},
	)
}
