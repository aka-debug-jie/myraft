package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"strings"
	"text/tabwriter"
	"time"

	wire "myraft/rpc"
)

func writeStatusTable(w io.Writer, states []wire.StatusReply) error {
	rows := append([]wire.StatusReply(nil), states...)
	sort.Slice(rows, func(i, j int) bool { return rows[i].ID < rows[j].ID })

	tw := tabwriter.NewWriter(w, 0, 4, 2, ' ', 0)
	if _, err := fmt.Fprintln(tw, "ID\tROLE(local)\tTERM\tLEADER\tLAST\tCOMMIT\tAPPLIED\tCOMMANDS\tX\tERROR"); err != nil {
		return err
	}
	for _, s := range rows {
		if s.Error != "" {
			errText := strings.NewReplacer("\n", " ", "\r", " ", "\t", " ").Replace(s.Error)
			if _, err := fmt.Fprintf(tw, "%d\t-\t-\t-\t-\t-\t-\t-\t-\t%s\n", s.ID, errText); err != nil {
				return err
			}
			continue
		}
		if _, err := fmt.Fprintf(tw, "%d\t%s\t%d\t%d\t%d\t%d\t%d\t%d/%d\t%d\t-\n",
			s.ID, s.State, s.Term, s.LeaderID, s.LastLogIndex, s.CommitIndex, s.LastApplied,
			s.CommittedCommands, s.AppliedCommands, s.X); err != nil {
			return err
		}
	}
	if _, err := fmt.Fprintln(tw, "Local role and reachability do not mean a write succeeded; only Generate accepted+committed confirms a write."); err != nil {
		return err
	}
	return tw.Flush()
}

// One query at a time; a slow query never accumulates refresh goroutines.
func watchStatuses(ctx context.Context, w io.Writer, query func() []wire.StatusReply, interval time.Duration, format string) error {
	for {
		if ctx.Err() != nil {
			return nil
		}
		states := query()
		if format == "table" {
			if _, err := fmt.Fprintf(w, "\nObserved at %s\n", time.Now().Format(time.RFC3339)); err != nil {
				return err
			}
			if err := writeStatusTable(w, states); err != nil {
				return err
			}
		} else if err := json.NewEncoder(w).Encode(states); err != nil {
			return err
		}
		timer := time.NewTimer(interval)
		select {
		case <-ctx.Done():
			timer.Stop()
			return nil
		case <-timer.C:
		}
	}
}
