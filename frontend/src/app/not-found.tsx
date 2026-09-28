import Link from "next/link";
import { SplitFlap } from "@/components/SplitFlap";
export default function NotFound() {
  return (
    <div className="mx-auto max-w-2xl py-16 text-center">
      <div className="mb-8 flex justify-center"><SplitFlap text="404" size={6} color="signal" framed /></div>
      <h1 className="display text-5xl">No such <em>stage.</em></h1>
      <p className="mx-auto mt-4 max-w-md text-ink2">That page isn&apos;t on the board. It may have been archived, or never scheduled.</p>
      <Link href="/events" className="btn btn-primary mt-8">Back to events</Link>
    </div>
  );
}
