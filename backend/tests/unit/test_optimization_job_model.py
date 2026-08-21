"""Unit tests for OptimizationJob SQLAlchemy model."""

from sqlalchemy import inspect as sa_inspect

from app.models.optimization_job import OptimizationJob


class TestOptimizationJobModel:
    def test_tablename(self):
        assert OptimizationJob.__tablename__ == "optimization_jobs"

    def test_required_columns_exist(self):
        mapper = sa_inspect(OptimizationJob)
        col_names = {c.key for c in mapper.mapper.column_attrs}
        expected = {
            "id",
            "owner_id",
            "status",
            "request",
            "character_name",
            "enemy_name",
            "rotation_name",
            "assignments_done",
            "assignments_total",
            "evaluated",
            "pruned_sets",
            "pruned_stats",
            "elapsed_seconds",
            "eta_seconds",
            "result",
            "top_damage",
            "error_message",
            "started_at",
            "finished_at",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(col_names)

    def test_nullable_columns(self):
        mapper = sa_inspect(OptimizationJob)
        cols = {c.key: c.columns[0] for c in mapper.mapper.column_attrs}
        assert cols["owner_id"].nullable is True
        assert cols["eta_seconds"].nullable is True
        assert cols["result"].nullable is True
        assert cols["top_damage"].nullable is True
        assert cols["error_message"].nullable is True
        assert cols["started_at"].nullable is True
        assert cols["finished_at"].nullable is True

    def test_non_nullable_columns(self):
        mapper = sa_inspect(OptimizationJob)
        cols = {c.key: c.columns[0] for c in mapper.mapper.column_attrs}
        assert cols["status"].nullable is False
        assert cols["request"].nullable is False

    def test_set_fields(self):
        job = OptimizationJob(
            status="running",
            request={"combo_id": "c1"},
            character_name="Zhu Yuan",
            enemy_name="Metal Crab",
            rotation_name="DPS Combo",
            assignments_done=5,
            assignments_total=20,
            evaluated=1000,
        )
        assert job.status == "running"
        assert job.character_name == "Zhu Yuan"
        assert job.enemy_name == "Metal Crab"
        assert job.assignments_done == 5
        assert job.assignments_total == 20
        assert job.evaluated == 1000

    def test_indexes_defined(self):
        table = OptimizationJob.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "ix_optimization_jobs_status" in index_names
        assert "ix_optimization_jobs_created_at_desc" in index_names
        assert "ix_optimization_jobs_job_type" in index_names

    def test_job_type_column_exists(self):
        mapper = sa_inspect(OptimizationJob)
        col_names = {c.key for c in mapper.mapper.column_attrs}
        assert "job_type" in col_names

    def test_job_type_non_nullable(self):
        mapper = sa_inspect(OptimizationJob)
        cols = {c.key: c.columns[0] for c in mapper.mapper.column_attrs}
        assert cols["job_type"].nullable is False

    def test_job_type_server_default_optimize(self):
        mapper = sa_inspect(OptimizationJob)
        cols = {c.key: c.columns[0] for c in mapper.mapper.column_attrs}
        sd = cols["job_type"].server_default
        assert sd is not None
        assert "optimize" in str(sd.arg)
