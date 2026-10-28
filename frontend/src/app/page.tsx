import Link from "next/link";

const capabilities = [
  {
    number: "01",
    title: "Company knowledge",
    description: "A focused home for the information your team needs to work with.",
  },
  {
    number: "02",
    title: "Grounded answers",
    description: "A foundation for trustworthy answers backed by your organization’s knowledge.",
  },
  {
    number: "03",
    title: "Built for teams",
    description: "A clear starting point for making company knowledge easier to explore.",
  },
];

export default function Home() {
  return (
    <main className="min-h-screen overflow-hidden bg-[#f7f8f6] text-[#17211c]">
      <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-6 sm:px-10">
        <header className="flex items-center justify-between border-b border-[#17211c]/10 py-6">
          <Link
            aria-label="KnowFlow AI home"
            className="flex items-center gap-3 font-semibold tracking-tight"
            href="/"
          >
            <span className="flex size-9 items-center justify-center rounded-xl bg-[#195c43] text-sm font-bold text-white">
              K
            </span>
            <span className="text-lg">KnowFlow <span className="text-[#668272]">AI</span></span>
          </Link>
          <span className="rounded-full border border-[#17211c]/10 px-3 py-1.5 text-xs font-medium tracking-wide text-[#526258]">
            FOUNDATION
          </span>
        </header>

        <section className="grid flex-1 items-center gap-14 py-20 lg:grid-cols-[1.1fr_0.9fr] lg:py-28">
          <div className="max-w-2xl">
            <p className="mb-6 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-[#28704f]">
              <span aria-hidden="true" className="size-2 rounded-full bg-[#54a777]" />
              Company knowledge, in flow
            </p>
            <h1 className="text-5xl font-semibold leading-[1.08] tracking-[-0.055em] sm:text-6xl lg:text-7xl">
              Find clarity in your company&apos;s knowledge.
            </h1>
            <p className="mt-7 max-w-xl text-lg leading-8 text-[#647168]">
              KnowFlow AI is the foundation for a more useful way to explore
              what your organization knows. Your team&apos;s knowledge, ready to
              flow.
            </p>
            <div className="mt-10 flex flex-wrap items-center gap-3">
              <a
                className="rounded-full bg-[#195c43] px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#124a35] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#195c43]"
                href="#foundation"
              >
                Explore the foundation
              </a>
              <span className="px-3 py-3 text-sm text-[#647168]">
                A new workspace starts here
              </span>
            </div>
          </div>

          <div
            aria-label="A preview of the KnowFlow AI knowledge workspace"
            className="relative mx-auto w-full max-w-lg"
          >
            <div aria-hidden="true" className="absolute -inset-8 rounded-[2.5rem] bg-[#e6eee8]" />
            <div className="relative rounded-[1.75rem] border border-[#17211c]/10 bg-white p-6 shadow-[0_24px_70px_-35px_rgba(23,33,28,0.3)] sm:p-8">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm font-semibold">Your knowledge space</p>
                  <p className="mt-1 text-xs text-[#829087]">A starting point for your team</p>
                </div>
                <span className="rounded-full bg-[#eaf4ed] px-2.5 py-1 text-[11px] font-medium text-[#28704f]">
                  GETTING STARTED
                </span>
              </div>
              <div className="mt-8 rounded-xl border border-dashed border-[#b9c9bd] bg-[#f8faf8] px-5 py-8 text-center">
                <span
                  aria-hidden="true"
                  className="mx-auto flex size-11 items-center justify-center rounded-full bg-[#e6eee8] text-xl text-[#28704f]"
                >
                  +
                </span>
                <p className="mt-4 text-sm font-semibold">Your workspace is ready</p>
                <p className="mx-auto mt-2 max-w-xs text-xs leading-5 text-[#829087]">
                  The essentials are in place. Your knowledge workflows can grow from here.
                </p>
              </div>
              <div className="mt-5 flex items-center gap-3 rounded-xl bg-[#f7f8f6] p-4">
                <span aria-hidden="true" className="size-2 rounded-full bg-[#54a777]" />
                <p className="text-xs text-[#647168]">Frontend and API foundations are ready to run</p>
              </div>
            </div>
          </div>
        </section>

        <section
          aria-labelledby="foundation-heading"
          className="border-t border-[#17211c]/10 py-12 sm:py-14"
          id="foundation"
        >
          <div className="mb-8 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#28704f]">
                The foundation
              </p>
              <h2
                className="mt-2 text-2xl font-semibold tracking-tight"
                id="foundation-heading"
              >
                Knowledge, made more useful.
              </h2>
            </div>
            <p className="max-w-md text-sm leading-6 text-[#647168]">
              A simple beginning for a thoughtful, AI-powered company knowledge experience.
            </p>
          </div>
          <div className="grid gap-4 pb-10 md:grid-cols-3">
            {capabilities.map((capability) => (
              <article
                className="rounded-2xl border border-[#17211c]/10 bg-white p-6"
                key={capability.number}
              >
                <p className="text-xs font-semibold tracking-widest text-[#7b8b80]">
                  {capability.number}
                </p>
                <h3 className="mt-5 font-semibold">{capability.title}</h3>
                <p className="mt-2 text-sm leading-6 text-[#647168]">
                  {capability.description}
                </p>
              </article>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
