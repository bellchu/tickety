"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { TicketList } from "@/components/ticket/TicketList";
import { NewTicketModal } from "@/components/ticket/NewTicketModal";
import { FetchTicketsModal } from "@/components/ticket/FetchTicketsModal";

export default function TicketsPage() {
  const [modalOpen, setModalOpen] = useState(false);
  const [fetchOpen, setFetchOpen] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-1.5">
          <h1 className="font-serif text-3xl text-ink-700">Tickets</h1>
          <p className="text-[13px] text-ink-500">
            Create and manage tickets directly in Tickety
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setModalOpen(true)}
            className="btn-primary text-xs"
          >
            <Plus className="w-4 h-4" strokeWidth={1.5} />
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