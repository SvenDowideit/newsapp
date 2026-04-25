package ui

import (
	"fmt"
	"math"
	"strings"
	"time"

	"github.com/SvenDowideit/newsapp/android/internal/api/models"
	"github.com/go-drift/drift/pkg/core"
	"github.com/go-drift/drift/pkg/graphics"
	"github.com/go-drift/drift/pkg/layout"
	"github.com/go-drift/drift/pkg/widgets"
)

const linesPerPage = 18

// ItemPage renders a single cluster item, paginated.
// onGesture is called with: "next_item","prev_item","discard","expand","menu","interest_up","interest_down"
func ItemPage(
	item *models.ClusterItem,
	expanded *models.ExpandedItem,
	currentPage int,
	onGesture func(string),
) core.Widget {
	if item == nil {
		return widgets.Center{Child: widgets.Text{Content: "No item", Style: BodyStyle()}}
	}

	var blocks []string
	blocks = append(blocks, item.Headline)
	blocks = append(blocks, "")

	// Use full_summary (from a previous expand) if available, else short summary
	body := item.Summary
	if item.FullSummary != nil && *item.FullSummary != "" {
		body = *item.FullSummary
	}
	blocks = append(blocks, body)

	if len(item.KeyPoints) > 0 {
		blocks = append(blocks, "")
		for _, kp := range item.KeyPoints {
			blocks = append(blocks, "• "+kp)
		}
	}
	if expanded != nil {
		blocks = append(blocks, "")
		blocks = append(blocks, "── More context ──")
		if expanded.Excerpt != nil && *expanded.Excerpt != "" {
			blocks = append(blocks, *expanded.Excerpt)
		} else {
			blocks = append(blocks, expanded.FullSummary)
		}
	}

	// Source URLs: prefer expanded urls, fall back to item's own
	urls := item.SourceURLs
	if expanded != nil && len(expanded.SourceURLs) > 0 {
		urls = expanded.SourceURLs
	}
	if len(urls) > 0 {
		blocks = append(blocks, "")
		for _, u := range urls {
			blocks = append(blocks, u)
		}
	}

	topics := strings.Join(item.Topics, " · ")
	interestPct := int(item.InterestScore * 100)
	meta := fmt.Sprintf("%s · %d sources · interest %d%%", topics, item.ItemCount, interestPct)
	if item.IsBreaking {
		meta = "BREAKING · " + meta
	} else if item.IsUpdate {
		meta = "UPDATE · " + meta
	}

	pages := paginateBlocks(blocks, linesPerPage)
	totalPages := len(pages)
	if currentPage >= totalPages {
		currentPage = totalPages - 1
	}
	if currentPage < 0 {
		currentPage = 0
	}
	pageContent := pages[currentPage]

	textWidgets := make([]core.Widget, 0, len(pageContent)+1)
	for i, line := range pageContent {
		if line == "" {
			textWidgets = append(textWidgets, widgets.VSpace(8))
		} else {
			style := BodyStyle()
			if i == 0 && currentPage == 0 {
				style = HeadlineStyle()
			}
			textWidgets = append(textWidgets, widgets.Text{Content: line, Style: style})
		}
	}

	// Bottom row: page counter, hint, interest buttons
	interestRow := widgets.Row{
		MainAxisAlignment: widgets.MainAxisAlignmentSpaceBetween,
		Children: []core.Widget{
			widgets.Text{
				Content: fmt.Sprintf("p%d/%d  ← → items  long-press menu", currentPage+1, totalPages),
				Style:   MetaStyle(),
			},
			widgets.Row{
				Children: []core.Widget{
					interestButton("−", func() { onGesture("interest_down") }),
					widgets.HSpace(12),
					interestButton("+", func() { onGesture("interest_up") }),
				},
			},
		},
	}

	body := widgets.Column{
		Children: append(textWidgets,
			widgets.Spacer(),
			widgets.Text{Content: meta, Style: MetaStyle()},
			widgets.Padding{
				Padding: layout.EdgeInsetsOnly(0, 6, 0, 0),
				Child:   interestRow,
			},
		),
	}

	// Swipe / long-press via pan gesture
	var panStart graphics.Offset
	var panStartTime time.Time

	return widgets.Padding{
		Padding: layout.EdgeInsetsAll(pagePadding),
		Child: widgets.GestureDetector{
			Child: body,
			OnTap: func() { onGesture("next_item") },
			OnPanStart: func(d widgets.DragStartDetails) {
				panStart = d.Position
				panStartTime = time.Now()
			},
			OnPanEnd: func(d widgets.DragEndDetails) {
				dx := d.Position.X - panStart.X
				dy := d.Position.Y - panStart.Y
				adx := math.Abs(dx)
				ady := math.Abs(dy)
				dur := time.Since(panStartTime)

				if adx < 15 && ady < 15 && dur > 600*time.Millisecond {
					onGesture("menu")
					return
				}
				const minSwipe = 60
				if adx > minSwipe && adx > ady {
					if dx < 0 {
						onGesture("discard")
					} else {
						onGesture("expand")
					}
				} else if ady > minSwipe && ady > adx {
					if dy < 0 {
						onGesture("next_item")
					} else {
						onGesture("prev_item")
					}
				}
			},
		},
	}
}

func interestButton(label string, onTap func()) core.Widget {
	return widgets.GestureDetector{
		OnTap: onTap,
		Child: widgets.Padding{
			Padding: layout.EdgeInsetsSymmetric(12, 6),
			Child:   widgets.Text{Content: label, Style: BoldBodyStyle()},
		},
	}
}

func paginateBlocks(blocks []string, maxLines int) [][]string {
	var pages [][]string
	var current []string
	for _, b := range blocks {
		current = append(current, b)
		if len(current) >= maxLines {
			pages = append(pages, current)
			current = nil
		}
	}
	if len(current) > 0 {
		pages = append(pages, current)
	}
	if len(pages) == 0 {
		pages = [][]string{{"(empty)"}}
	}
	return pages
}
