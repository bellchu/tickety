"use client";

import { useState } from "react";
import { Plus, Download } from "lucide-react";
import { TicketList } from "@/components/ticket/TicketList";
import { NewTicketModal } from "@/components/ticket/NewTicketModal";
import { FetchTicketsModal } from "@/components/ticket/FetchTicketsModal";

export default function TicketsPage() {
  const [modalOpen, setModalOpen] = useState(false);
  const [fetchOpen, setFetchOpen] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Tickets</h1>
          <p className="text-sm text-slate-500 mt-1">
            Synced from Freshservice or created manually
          </p>
        </div>
          <div className="flex items-center gap-2">
          <button
            onClick={() => setFetchOpen(true)}
            className="btn-secondary text-xs"
          >
            <Download className="w-4 h-4" />
            Fetch Tickets
          </button>
          <button
            onClick={() => setModalOpen(true)}
            className="btn-primary text-xs"
          >
            <Plus className="w-4 h-4" />
            New Ticket
          </button>
        </div>
      </div>

      <TicketList />

      <NewTicketModal open={modalOpen} onClose={() => setModalOpen(false)} />
      <FetchTicketsModal open={fetchOpen} onClose={() => setFetchOpen(false)} />
    </div>
  );
}