import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AuthBoundary } from "../auth/AuthBoundary";
import { AppShell } from "../components/layout/AppShell";
import { CasePage } from "./CasePage";
import { DemoPage } from "./DemoPage";
import { IndexPage } from "./IndexPage";
import { NotFoundPage } from "./NotFoundPage";
import { PurchaseApprovePage } from "./PurchaseApprovePage";
import { PurchasePage } from "./PurchasePage";
import { SearchPage } from "./SearchPage";

const router = createBrowserRouter([
  {
    element: (
      <AuthBoundary>
        <AppShell />
      </AuthBoundary>
    ),
    children: [
      { path: "/", element: <IndexPage /> },
      { path: "/searches/:id", element: <SearchPage /> },
      { path: "/purchases/:id/approve", element: <PurchaseApprovePage /> },
      { path: "/purchases/:id", element: <PurchasePage /> },
      { path: "/cases/:id", element: <CasePage /> },
      { path: "/demo", element: <DemoPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
