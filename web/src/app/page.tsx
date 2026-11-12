import { HealthStatus } from "@/components/HealthStatus";

export default function HomePage() {
  return (
    <div className="flex flex-col gap-8">
      <section>
        <h1 className="text-3xl font-bold tracking-tight text-navy dark:text-white">
          Your media, organized.
        </h1>
        <p className="mt-2 max-w-2xl text-slate-600 dark:text-slate-300">
          MediaVault will let you import, preview, organize and convert your own photos, videos
          and audio on Android and the web. This build is Phase 1: it proves the website can reach
          the shared MediaVault server.
        </p>
      </section>
      <HealthStatus />
    </div>
  );
}
