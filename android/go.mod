module github.com/svenDowideit/newsapp

go 1.22

require (
	github.com/go-drift/drift v0.0.0-00010101000000-000000000000
	go.etcd.io/bbolt v1.3.9
)

// Drift is pre-release; replace directive lets us pin to main until a tag exists.
// Run: go get github.com/go-drift/drift@main
// then remove this replace block.
replace github.com/go-drift/drift => github.com/go-drift/drift v0.0.0-latest
