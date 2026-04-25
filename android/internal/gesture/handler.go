package gesture

import (
	"math"
	"time"
)

// GestureType identifies a recognised gesture.
type GestureType int

const (
	GestureNone GestureType = iota
	GestureTapLeft
	GestureTapRight
	GestureSwipeUp
	GestureSwipeDown
	GestureSwipeLeft
	GestureSwipeRight
	GestureLongPress
)

// Thresholds (in logical pixels / dp).
const (
	swipeMinDist  = 60.0
	tapMaxDist    = 15.0
	tapZoneFrac   = 0.35 // left/right 35% of width = zone tap
	longPressDur  = 600 * time.Millisecond
)

// Point is a 2-D position.
type Point struct{ X, Y float32 }

// Classifier accumulates pointer events and classifies gestures.
type Classifier struct {
	downPos  Point
	downTime time.Time
	active   bool
}

// Press records a pointer-down event at the given position.
func (g *Classifier) Press(pos Point) {
	g.downPos = pos
	g.downTime = time.Now()
	g.active = true
}

// Release classifies the gesture when the pointer is lifted.
// screenW is the full screen width in logical pixels.
func (g *Classifier) Release(pos Point, screenW float32) GestureType {
	if !g.active {
		return GestureNone
	}
	g.active = false

	dx := pos.X - g.downPos.X
	dy := pos.Y - g.downPos.Y
	dist := math.Sqrt(float64(dx*dx + dy*dy))
	dur := time.Since(g.downTime)

	if dist < tapMaxDist {
		if dur >= longPressDur {
			return GestureLongPress
		}
		if g.downPos.X < screenW*tapZoneFrac {
			return GestureTapLeft
		}
		if g.downPos.X > screenW*(1-tapZoneFrac) {
			return GestureTapRight
		}
		// Centre tap — treat as right (advance)
		return GestureTapRight
	}

	// Swipe: dominant axis wins
	if math.Abs(float64(dx)) > math.Abs(float64(dy)) {
		if dx < -swipeMinDist {
			return GestureSwipeLeft
		}
		if dx > swipeMinDist {
			return GestureSwipeRight
		}
	} else {
		if dy < -swipeMinDist {
			return GestureSwipeUp
		}
		if dy > swipeMinDist {
			return GestureSwipeDown
		}
	}
	return GestureNone
}

// Cancel resets state without classifying.
func (g *Classifier) Cancel() { g.active = false }
