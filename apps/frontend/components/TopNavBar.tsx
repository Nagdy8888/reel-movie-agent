import Link from "next/link";

/** Top navigation bar for the landing page. */
export function TopNavBar() {
  return (
    <header className="bg-background/80 backdrop-blur-xl fixed top-0 w-full z-50 border-b border-outline-variant/30 transition-all duration-300">
      <div className="flex justify-between items-center px-margin-mobile md:px-margin-desktop py-md max-w-[1600px] mx-auto w-full">
        <div className="flex items-center gap-xl">
          <Link
            href="/"
            className="font-display-md text-display-md font-bold text-primary tracking-tight"
          >
            Reel
          </Link>
          <nav className="hidden md:flex gap-lg">
            <a
              href="#discover"
              className="font-body-lg text-body-lg text-primary font-bold border-b-2 border-primary pb-1 cursor-pointer active:scale-95 transition-colors duration-300"
            >
              Discover
            </a>
            <a
              href="#features"
              className="font-body-lg text-body-lg text-on-surface-variant hover:text-primary cursor-pointer active:scale-95 transition-colors duration-300 pb-1 border-b-2 border-transparent"
            >
              Features
            </a>
            <a
              href="#library"
              className="font-body-lg text-body-lg text-on-surface-variant hover:text-primary cursor-pointer active:scale-95 transition-colors duration-300 pb-1 border-b-2 border-transparent"
            >
              Library
            </a>
          </nav>
        </div>
        <div className="flex items-center gap-md">
          <Link
            href="/login"
            className="bg-primary-container text-on-primary-container font-title-md text-title-md px-lg py-sm rounded hover:brightness-110 transition-all active:scale-95 font-semibold"
          >
            Sign In
          </Link>
        </div>
      </div>
    </header>
  );
}
