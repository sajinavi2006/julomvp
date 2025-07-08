class TaskMixin:
    PROVIDER_TONGDUN = "tongdun"
    PROVIDER_BRICK = "brick"
    PROVIDERS = (PROVIDER_TONGDUN, PROVIDER_BRICK)

    _provider_ = None

    @property
    def provider(self):
        return self._provider_

    @provider.setter
    def provider(self, provider):
        if provider not in self.PROVIDERS:
            raise LookupError("Bpjs provider not found.")

        self._provider_ = provider

    def guess_provider(self):
        """
        To guess the provider we look relations into table ops.bpjs_task.
        Inside it define the provider of the bpjs.
        """

        # Check from Tongdun
        from juloserver.bpjs.models import BpjsTask

        tasks = BpjsTask.objects.filter(application=self.application)
        if tasks.count() >= 1:
            return self.PROVIDER_TONGDUN

        # Check from Brick
        # todo: check into new table if already created
        return self.PROVIDER_BRICK

    def using_provider(self, provider):
        """
        If setter not convenient you can use chained method to set the provider.
        Example:
            bpjs = Bpjs()
            bpjs.using_provider('brick').authenticate()
        """
        self.provider = provider
        return self
