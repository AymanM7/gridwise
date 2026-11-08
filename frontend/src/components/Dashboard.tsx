"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAdvice, fetchForecast, fetchHealth, fetchHistory, fetchReportCard } from "../lib/api";
import { LEVEL_COLOR, sameInstant } from "../lib/format";
import { AuroraBackground } from "./shader/Backgrounds";
import Header from "./Header";
import StrainTimeline from "./StrainTimeline";
import WhyRedPanel from "./WhyRedPanel";
import SpikeChart from "./SpikeChart";
import BestHoursCard from "./BestHoursCard";
import AdvicePanel, { AdviceBadge } from "./AdvicePanel";
import RipplePanel from "./RipplePanel";
import ReportCard from "./ReportCard";
import HistoryChart from "./HistoryChart";
import ChatBox from "./ChatBox";
import Footer from "./Footer";
import { Card, Empty, ErrorBox, Loading } from "./ui";
import TopBar, { type NavItem } from "./hero/TopBar";
import {
  Activity,
  CalendarDays,
  ClipboardCheck,
  Clock3,
  ListChecks,
  MessagesSquare,
  ScanSearch,
  TrendingUp,
  WavesHorizontal,
} from "lucide-react";

const NAV: NavItem[] = [
  { id: "timeline", label: "Timeline" },
  { id: "plan", label: "Plan" },
  { id: "spikes", label: "Spikes" },
  { id: "ask", label: "Ask" },
  { id: "ripple", label: "Ripple" },
  { id: "accuracy", label: "Accuracy" },
];

function errMsg(e: unknown) {
  return e instanceof Error ? e.message : "Something went wrong";
}

export default function Dashboard() {
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth });
  const forecast = useQuery({ queryKey: ["forecast"], queryFn: () => fetchForecast(48) });
  const advice = useQuery({ queryKey: ["advice"], queryFn: fetchAdvice });
  const report = useQuery({ queryKey: ["report-card"], queryFn: () => fetchReportCard(7), staleTime: 60 * 60_000 });
  const history = useQuery({ queryKey: ["history"], queryFn: () => fetchHistory(30), staleTime: 60 * 60_000 });

  const fc = forecast.data?.data;
  const [selected, setSelected] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<string[]>([]);
  const timelineRef = useRef<HTMLDivElement>(null);
  const whyRef = useRef<HTMLDivElement>(null);

  // Preselect the most strained hour so "Why red?" is visible on first load.
  useEffect(() => {
    if (fc && selected == null && fc.hours.length) {
      const top = [...fc.hours].sort((a, b) => b.strain_index - a.strain_index)[0];
      setSelected(top.target_ts);
    }
  }, [fc, selected]);

  const selHour = useMemo(
    () => (fc && selected ? (fc.hours.find((h) => sameInstant(h.target_ts, selected)) ?? null) : null),
    [fc, selected],
  );
  const whyFallback = useMemo(() => {
    const map = advice.data?.data.why_red;
    if (!map || !selected) return undefined;
    const k = Object.keys(map).find((t) => sameInstant(t, selected));
    return k ? map[k] : undefined;
  }, [advice.data, selected]);

  // Background aurora takes the color of tomorrow's worst strain level.
  const peakTint = useMemo(() => {
    const c = fc?.summary.level_counts;
    if (!c) return "#7dd3fc";
    return LEVEL_COLOR[c.red > 0 ? "red" : c.yellow > 0 ? "yellow" : "green"];
  }, [fc]);

  function select(ts: string) {
    setSelected(ts);
    if (window.matchMedia("(max-width: 1023px)").matches) {
      whyRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function onHighlight(ts: string[]) {
    setHighlight(ts);
    if (ts.length) timelineRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <>
      <AuroraBackground tint={peakTint} />
      <span id="top" className="absolute top-0" aria-hidden />
      <TopBar items={NAV} />
      <main className="mx-auto max-w-7xl space-y-6 px-4 pb-12 pt-4 sm:space-y-8 sm:px-6 sm:pt-6">
        <Header forecast={fc} health={health.data?.data} source={forecast.data?.source} loading={forecast.isPending} />

        {/* 1 · Explore the next 48 hours */}
        <div id="timeline" className="grid scroll-mt-20 grid-cols-1 gap-6 lg:grid-cols-3">
          <div ref={timelineRef} className="min-w-0 scroll-mt-20 lg:col-span-2">
            <Card eyebrow="Forecast" title="48-hour strain timeline" icon={<Activity />}>
              {forecast.isPending ? (
                <Loading label="Loading forecast" className="h-80" />
              ) : forecast.isError ? (
                <ErrorBox message={`Couldn't load the forecast: ${errMsg(forecast.error)}`} onRetry={() => forecast.refetch()} />
              ) : fc && fc.hours.length ? (
                <StrainTimeline hours={fc.hours} selected={selected} onSelect={select} highlight={highlight} />
              ) : (
                <Empty>No forecast available yet. The hourly pipeline will publish one shortly.</Empty>
              )}
            </Card>
          </div>
          <div ref={whyRef} className="min-w-0 scroll-mt-20">
            <Card eyebrow="Explain" title="Why this color?" icon={<ScanSearch />}>
              <WhyRedPanel hour={selHour} whyRedFallback={whyFallback} onClose={() => setSelected(null)} />
            </Card>
          </div>
        </div>

        {/* 2 · Plan the day */}
        <div id="plan" className="scroll-mt-20">
          <Card eyebrow="Plan" title="Best hours" icon={<Clock3 />}>
            {forecast.isPending ? <Loading className="h-28" /> : fc ? <BestHoursCard forecast={fc} /> : <Empty>No forecast.</Empty>}
          </Card>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <div className="min-w-0 lg:col-span-3">
            <Card
              eyebrow="Plan"
              title="Your plan"
              icon={<ListChecks />}
              right={advice.data ? <AdviceBadge by={advice.data.data.generated_by} /> : null}
            >
              {advice.isPending ? (
                <Loading label="Loading advice" className="h-48" />
              ) : advice.isError ? (
                <ErrorBox message={`Couldn't load advice: ${errMsg(advice.error)}`} onRetry={() => advice.refetch()} />
              ) : advice.data ? (
                <AdvicePanel advice={advice.data.data} />
              ) : null}
            </Card>
          </div>

          {/* 3 · Price risk + ask */}
          <div className="flex min-w-0 flex-col gap-6 lg:col-span-2">
            <div id="spikes" className="scroll-mt-20">
              <Card eyebrow="Price" title="Spike risk" icon={<TrendingUp />}>
                {forecast.isPending ? (
                  <Loading className="h-56" />
                ) : fc && fc.hours.length ? (
                  <SpikeChart hours={fc.hours} onSelect={select} />
                ) : (
                  <Empty>No spike forecast available.</Empty>
                )}
              </Card>
            </div>
            <div id="ask" className="flex-1 scroll-mt-20">
              <Card eyebrow="Assistant" title="Ask GridWise" icon={<MessagesSquare />}>
                <ChatBox forecast={fc} onHighlight={onHighlight} />
              </Card>
            </div>
          </div>
        </div>

        {/* 4 · Community impact */}
        <div id="ripple" className="scroll-mt-20">
          <Card eyebrow="What if" title="Ripple: what if Texas shifted?" icon={<WavesHorizontal />}>
            <RipplePanel forecast={fc} />
          </Card>
        </div>

        {/* 5 · Trust */}
        <div id="accuracy" className="grid scroll-mt-20 grid-cols-1 gap-6 lg:grid-cols-2">
          <Card eyebrow="Accuracy" title="Report card" icon={<ClipboardCheck />}>
            {report.isPending ? (
              <Loading className="h-40" />
            ) : report.isError ? (
              <ErrorBox message={`Couldn't load the report card: ${errMsg(report.error)}`} onRetry={() => report.refetch()} />
            ) : report.data ? (
              <ReportCard rc={report.data.data} />
            ) : null}
          </Card>
          <Card eyebrow="History" title="Last 30 days" icon={<CalendarDays />}>
            {history.isPending ? (
              <Loading className="h-56" />
            ) : history.isError ? (
              <ErrorBox message={`Couldn't load history: ${errMsg(history.error)}`} onRetry={() => history.refetch()} />
            ) : history.data ? (
              <HistoryChart history={history.data.data} />
            ) : null}
          </Card>
        </div>

        <Footer />
      </main>
    </>
  );
}
