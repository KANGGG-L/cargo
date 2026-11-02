

# ---------------------------------------------------------------- map (F2)


class Location(Base):
    """Facility coordinates for the map view (ports / airports / checkpoints)."""

    __tablename__ = "dim_locations"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(12))  # seaport | airport | checkpoint
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)


# ---------------------------------------------------------------- map (F2)


class Location(Base):
    """Facility coordinates for the map view (ports / airports / checkpoints)."""

    __tablename__ = "dim_locations"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(12))  # seaport | airport | checkpoint
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
