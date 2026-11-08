"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAdvice, fetchForecast, fetchHealth, fetchHistory, fetchReportCard } from "../lib/api";
import { sameInstant } from "../lib/format";
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
    <main className="mx-auto max-w-6xl space-y-4 px-4 py-5 sm:space-y-5 sm:px-6 sm:py-8">
      <Header forecast={fc} health={health.data?.data} source={forecast.data?.source} loading={forecast.isLoading} />

      <div className="grid grid-cols-1 gap-4 sm:gap-5 lg:grid-cols-3">
        <div className="min-w-0 space-y-4 sm:space-y-5 lg:col-span-2">
          <div ref={timelineRef} className="scroll-mt-4">
            <Card title="48-hour strain timeline" icon="🚦">
              {forecast.isLoading ? (
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

          <Card title="Spike risk" icon="💸">
            {forecast.isLoading ? (
              <Loading className="h-44" />
            ) : fc && fc.hours.length ? (
              <SpikeChart hours={fc.hours} onSelect={select} />
            ) : (
              <Empty>No spike forecast available.</Empty>
            )}
          </Card>
        </div>

        <div className="min-w-0 space-y-4 sm:space-y-5">
          <div ref={whyRef} className="scroll-mt-4">
            <Card title="Why this color?" icon="❓">
              <WhyRedPanel hour={selHour} whyRedFallback={whyFallback} onClose={() => setSelected(null)} />
            </Card>
          </div>
          <Card title="Your plan" icon="🤖" right={advice.data ? <AdviceBadge by={advice.data.data.generated_by} /> : null}>
            {advice.isLoading ? (
              <Loading label="Loading advice" className="h-48" />
            ) : advice.isError ? (
              <ErrorBox message={`Couldn't load advice: ${errMsg(advice.error)}`} onRetry={() => advice.refetch()} />
            ) : advice.data ? (
              <AdvicePanel advice={advice.data.data} />
            ) : null}
          </Card>
        </div>
      </div>

      <Card title="Best hours" icon="🕐">
        {forecast.isLoading ? <Loading className="h-28" /> : fc ? <BestHoursCard forecast={fc} /> : <Empty>No forecast.</Empty>}
      </Card>

      <Card title="Ask GridWise" icon="💬">
        <ChatBox forecast={fc} onHighlight={onHighlight} />
      </Card>

      <Card title="Ripple: what if Texas shifted?" icon="🌊">
        <RipplePanel forecast={fc} />
      </Card>

      <div className="grid grid-cols-1 gap-4 sm:gap-5 lg:grid-cols-2">
        <Card title="Report card" icon="📊">
          {report.isLoading ? (
            <Loading className="h-40" />
          ) : report.isError ? (
            <ErrorBox message={`Couldn't load the report card: ${errMsg(report.error)}`} onRetry={() => report.refetch()} />
          ) : report.data ? (
            <ReportCard rc={report.data.data} />
          ) : null}
        </Card>
        <Card title="Last 30 days" icon="📈">
          {history.isLoading ? (
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
  );
}
