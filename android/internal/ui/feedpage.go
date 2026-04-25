package ui

import (
	"fmt"
	"strings"

	"github.com/SvenDowideit/newsapp/android/internal/api/models"
	"github.com/go-drift/drift/pkg/core"
	"github.com/go-drift/drift/pkg/layout"
	"github.com/go-drift/drift/pkg/widgets"
)
// FeedPage renders the list of items in the feed.
// onSelect is called with the item index when an item is tapped.
func FeedPage(items []models.ClusterItem, onSelect func(int)) core.Widget {
	if len(items) == 0 {
		return widgets.Center{
			Child: widgets.Text{Content: "Loading feed…", Style: MetaStyle()},
		}
	}

	rows := make([]core.Widget, 0, len(items)*2)
	for i, item := range items {
		idx := i
		it := item

		headline := it.Headline
		if it.IsBreaking {
			headline = "BREAKING  " + headline
		} else if it.IsUpdate {
			headline = "UPDATE  " + headline
		}

		interestPct := int(it.InterestScore * 100)

		sourceStr := strings.Join(it.SourceIDs, ", ")
		if len(it.SourceIDs) == 0 {
			sourceStr = "unknown"
		}

		row := widgets.GestureDetector{
			OnTap: func() { onSelect(idx) },
			Child: widgets.Padding{
				Padding: layout.EdgeInsetsAll(pagePadding),
				Child: widgets.Column{
					Children: []core.Widget{
						widgets.Text{Content: headline, Style: HeadlineStyle()},
						widgets.VSpace(6),
						widgets.Text{Content: it.Summary, Style: BodyStyle()},
						widgets.VSpace(4),
						widgets.Text{
							Content: fmt.Sprintf("%s · %d sources · interest %d%%", sourceStr, it.ItemCount, interestPct),
							Style:   MetaStyle(),
						},
					},
				},
			},
		}
		rows = append(rows, row, widgets.Divider{})
	}

	return widgets.ScrollView{
		Child: widgets.Column{Children: rows},
	}
}
